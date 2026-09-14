import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import transform


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'test.duckdb'
        self.meta = {'objectIdField': 'FID', 'fields': [
            {'name': 'FID', 'type': 'esriFieldTypeOID'},
            {'name': 'LURBSTATUS', 'domain': {'codedValues': [{'code': 'APR', 'name': 'Approved'}]}},
        ]}

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, run='20260908', duplicate=False):
        directory = self.root / run
        directory.mkdir()
        layer = dict(layer_id='map:1', source_id='s', kind='interim', category='village_center_buffer',
                     stage='interim', rpc=None, path=['III.) Village Center & Buffer'], where='1=1', map_definition={})
        features = [dict(type='Feature', properties={
            'FID': 1, 'DIS_NAME': 'Example', 'GEOID': '000001',
            'ExemptionApplied_Y_N_': 'N', 'DW_Status': 'Y', 'WW_Status': 'N',
            'AdequateSoils': 'unknown', 'TIER_VERS': 'APP', 'LURBSTATUS': 'APR',
            'ExtraField': 'keep this',
        }, geometry={'type': 'Point', 'coordinates': [-72.123456789, 44.123456789]})]
        if duplicate:
            features *= 2
        transform.write_json(directory / 's.geojson', {'type': 'FeatureCollection', 'features': features})
        transform.write_json(directory / 's_meta.json', self.meta)
        manifest = dict(schema_version=1, run_id=run, started_at=run[:4]+'-09-08T00:00:00Z',
                        completed_at='2026-09-08T00:00:01Z', layers=[layer], sources=[dict(
                            source_id='s', url='https://example.test/0', count=len(features), memberships={'map:1': [1]})],
                        files={p.name: transform.sha256(p) for p in directory.iterdir()})
        transform.write_json(directory / 'manifest.json', manifest)
        return directory

    def load(self, directory):
        with contextlib.redirect_stdout(io.StringIO()):
            transform.load_snapshot(directory, self.db)

    def test_structured_fields_geometry_and_idempotence(self):
        directory = self.fixture()
        self.load(directory)
        self.load(directory)
        with duckdb.connect(str(self.db)) as con:
            con.execute('LOAD spatial')
            row = con.execute('''SELECT likely_eligible, drinking_water, sewer_wastewater,
                zoning_bylaws, adequate_soils, geoid, submission_version, lurb_status,
                raw_properties->>'ExtraField', decoded_properties->>'LURBSTATUS', ST_X(geom)
                FROM interim_areas''').fetchall()
            self.assertEqual(row, [(False, True, False, None, None, '000001', 'APP', 'APR',
                                    'keep this', 'Approved', -72.123456789)])
            self.assertEqual(con.execute('SELECT count(*) FROM ingest_runs').fetchone()[0], 1)

    def test_failed_load_keeps_previous_snapshot(self):
        self.load(self.fixture())
        with self.assertRaises(duckdb.ConstraintException):
            self.load(self.fixture('20270908', duplicate=True))
        with duckdb.connect(str(self.db)) as con:
            self.assertEqual(con.execute('SELECT run_id FROM latest_ingest_run').fetchone()[0], '20260908')

    def test_checksum_failure(self):
        directory = self.fixture()
        (directory / 's.geojson').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            self.load(directory)

    def test_restore_never_writes_snapshot_or_calls_network(self):
        directory = self.fixture()
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        original_open = Path.open
        def readonly_snapshot(path, mode='r', *args, **kwargs):
            if path.parent == directory and any(flag in mode for flag in ('w', 'a', '+', 'x')):
                raise AssertionError('Snapshot write attempted')
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', readonly_snapshot), \
                patch('extract.capture', side_effect=AssertionError('unexpected capture')), \
                patch('arcgis.fetch_json', side_effect=AssertionError('unexpected network')):
            self.load(directory)
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)

    def test_missing_geometry_is_retained(self):
        directory = self.fixture()
        data = json.loads((directory / 's.geojson').read_text())
        data['features'][0]['geometry'] = None
        transform.write_json(directory / 's.geojson', data)
        manifest = json.loads((directory / 'manifest.json').read_text())
        manifest['files']['s.geojson'] = transform.sha256(directory / 's.geojson')
        transform.write_json(directory / 'manifest.json', manifest)
        self.load(directory)
        with duckdb.connect(str(self.db)) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM current_features WHERE geom IS NULL').fetchone()[0], 1)

    def test_empty_source_remains_in_catalog(self):
        directory = self.fixture()
        transform.write_json(directory / 's.geojson', {'type': 'FeatureCollection', 'features': []})
        manifest = json.loads((directory / 'manifest.json').read_text())
        manifest['sources'][0].update(count=0, memberships={'map:1': []})
        manifest['files']['s.geojson'] = transform.sha256(directory / 's.geojson')
        transform.write_json(directory / 'manifest.json', manifest)
        self.load(directory)
        with duckdb.connect(str(self.db)) as con:
            self.assertEqual(con.execute('SELECT feature_count FROM current_layers').fetchone()[0], 0)
            self.assertEqual(con.execute('SELECT count(*) FROM current_features').fetchone()[0], 0)

    def test_stage_is_independent_from_approval(self):
        source = dict(source_id='s', url='https://example.test')
        layer = dict(source_id='s', kind='tier', category='tier', stage='application', rpc='CC', path=['Tier 1B'])
        row = transform.normalize({'properties': {'FID': 9, 'TIER_VERS': 'APP', 'LURBSTATUS': 'APR'}, 'geometry': None},
                               self.meta, source, [layer], 'r')
        self.assertEqual((row['submission_version'], row['lurb_status'], row['tier_code']), ('APP', 'APR', '1B'))

    def test_boundary_fields_are_normalized_without_losing_raw_attributes(self):
        source = dict(source_id='s', url='https://example.test')
        municipal_layer = dict(source_id='s', kind='municipality_boundary',
                               category='municipality_boundary', stage='reference', rpc=None,
                               path=['VT Data - Town Boundaries'])
        municipal = transform.normalize({'properties': {
            'FID': 1, 'TOWNNAME': 'BURLINGTON', 'TOWNNAMEMC': 'Burlington',
            'TOWNGEOID': '5000710675', 'CNTY': 7,
        }, 'geometry': None}, self.meta, source, [municipal_layer], 'r')
        self.assertEqual((municipal['name'], municipal['municipality'], municipal['geoid']),
                         ('Burlington', 'Burlington', '5000710675'))
        self.assertEqual(municipal['raw_properties']['CNTY'], 7)

        rpc_layer = dict(source_id='s', kind='rpc_boundary', category='rpc_boundary',
                         stage='reference', rpc=None,
                         path=['VT Data - RPC Boundaries'])
        rpc = transform.normalize({'properties': {
            'FID': 2, 'RPC': 'CC', 'INITIALS': 'CCRPC',
            'LONGNAME': 'Chittenden County Regional Planning Commission',
        }, 'geometry': None}, self.meta, source, [rpc_layer], 'r')
        self.assertEqual((rpc['rpc'], rpc['name']),
                         ('CC', 'Chittenden County Regional Planning Commission'))


