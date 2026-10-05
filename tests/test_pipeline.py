"""Offline pipeline contracts and failure-safe publication."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from analyze import publish_json_directory
from analyze import build
from analyze import export_all, export_housing_growth
from transform import prepare, load_prepared
import transform
import extract


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'research.duckdb'
        self.memberships = self.root / 'memberships.json'
        self.output = self.root / 'dashboard'
        with duckdb.connect(str(self.db)) as con:
            con.execute('LOAD spatial')
            con.execute("CREATE TABLE latest_ingest_run AS SELECT 'capture' AS run_id, TIMESTAMPTZ '2026-09-08 00:00:00+00' AS completed_at")
            con.execute("CREATE TABLE interim_areas AS SELECT 'area' AS feature_id, '1' AS source_oid, 'Town' AS municipality, 'Center' AS name, 'downtown_district' AS category, 'Downtown' AS exemption_type, true AS likely_eligible, NULL::BOOLEAN AS zoning_bylaws, false AS drinking_water, true AS sewer_wastewater, NULL::BOOLEAN AS adequate_soils, NULL::GEOMETRY AS geom")
            con.execute("CREATE TABLE current_features AS SELECT 'town' AS feature_id, 'Town' AS name, 'Town' AS municipality, '001' AS geoid, 'municipality_boundary' AS kind, NULL::VARCHAR AS rpc, NULL::GEOMETRY AS geom")
            con.execute("UPDATE current_features SET geom=ST_GeomFromText('POLYGON((-73 44,-72.9 44,-72.9 44.1,-73 44.1,-73 44))')")
            con.execute("INSERT INTO current_features VALUES ('rpc','Region',NULL,NULL,'rpc_boundary','RR',ST_GeomFromText('POLYGON((-74 43,-72 43,-72 45,-74 45,-74 43))'))")
            con.execute("CREATE VIEW municipal_boundaries AS SELECT * FROM current_features WHERE kind='municipality_boundary'")
            con.execute("CREATE VIEW rpc_boundaries AS SELECT * FROM current_features WHERE kind='rpc_boundary'")
            con.execute('CREATE TABLE ingest_sources (run_id VARCHAR, source_id VARCHAR, url VARCHAR)')
            con.execute('CREATE TABLE current_layers (run_id VARCHAR, source_id VARCHAR, kind VARCHAR)')
            con.execute('''CREATE TABLE map_features (run_id VARCHAR, feature_id VARCHAR,
                source_id VARCHAR, source_oid VARCHAR, layer_id VARCHAR, rpc VARCHAR,
                name VARCHAR, map_stage VARCHAR, submission_version VARCHAR,
                lurb_status VARCHAR, geometry_valid BOOLEAN, geom GEOMETRY,
                kind VARCHAR, tier_code VARCHAR, flu_code VARCHAR, date_lurb VARCHAR)''')
            transform.create_tier1b_working_view(con)

    def export(self):
        prepare(self.db, self.memberships)
        transform.prepare_tier(self.db)
        transform.prepare_housing_growth(self.db)
        export_all(self.db, self.output / 'data', self.memberships)

    def test_working_tier_selects_whole_rpc_stage_and_preserves_status_and_null_geometry(self):
        with duckdb.connect(str(self.db)) as con:
            con.execute('LOAD spatial')
            con.execute('''INSERT INTO map_features
                (feature_id, rpc, kind, tier_code, map_stage, submission_version, lurb_status)
                VALUES ('old', 'NW', 'tier', '1B', 'pre_application', 'PRE', NULL),
                  ('app', 'NW', 'tier', '1B', 'application', 'APP', 'APR'),
                  ('approved', 'NW', 'tier', '1B', 'approved', 'APP', 'APR'),
                  ('ma-old', 'MA', 'tier', '1B', 'pre_application', 'PRE', NULL),
                  ('ma-a', 'MA', 'tier', '1B', 'application', 'APP', NULL),
                  ('ma-b', 'MA', 'tier', '1B', 'application', 'APP', NULL),
                  ('ac', 'AC', 'tier', '1B', 'pre_application', 'PRE', NULL),
                  ('other-tier', 'AC', 'tier', '1A', 'approved', 'APP', 'APR')''')
            rows = con.execute('''SELECT feature_id FROM tier1b_working
                                  ORDER BY feature_id''').fetchall()
            self.assertEqual(rows, [('ac',), ('approved',), ('ma-a',), ('ma-b',)])
            self.assertEqual(con.execute('''SELECT submission_version, lurb_status, geom
                FROM tier1b_working WHERE rpc = 'NW' ''').fetchone(), ('APP', 'APR', None))

    def test_preparation_is_read_only_and_stale_inputs_fail(self):
        before = self.db.read_bytes()
        prepare(self.db, self.memberships)
        self.assertEqual(self.db.read_bytes(), before)
        stamp = self.memberships.stat().st_mtime_ns
        prepare(self.db, self.memberships)
        self.assertEqual(self.memberships.stat().st_mtime_ns, stamp)
        with duckdb.connect(str(self.db)) as con:
            self.assertEqual(len(load_prepared(con, self.memberships)), 1)
            with patch('transform.MEMBERSHIP_VERSION', 99):
                with self.assertRaisesRegex(ValueError, 'Stale'):
                    load_prepared(con, self.memberships)

            con.execute("UPDATE interim_areas SET municipality = 'Changed'")
            with self.assertRaisesRegex(ValueError, 'Stale'):
                load_prepared(con, self.memberships)

    def test_spatial_tier_preserves_spillover_splits_real_crossing_and_removes_tiny_parts(self):
        with duckdb.connect(str(self.db)) as con:
            con.execute('LOAD spatial')
            def rectangle(x1,y1,x2,y2):
                return f'POLYGON(({x1} {y1},{x2} {y1},{x2} {y2},{x1} {y2},{x1} {y1}))'
            def wgs(wkt):
                return con.execute("SELECT ST_AsWKB(ST_Transform(ST_GeomFromText(?),'EPSG:32145','EPSG:4326',always_xy:=true))",[wkt]).fetchone()[0]
            con.execute('DELETE FROM current_features')
            for geoid,name,x in [('001','West',400000),('002','East',401000)]:
                con.execute("INSERT INTO current_features VALUES (?,?,?,?,'municipality_boundary','RR',ST_GeomFromWKB(?))",
                            [geoid,name,name,geoid,wgs(rectangle(x,150000,x+1000,151000))])
            for fid,stage,shape in [('spill','approved',rectangle(400800,150200,401050,150400)),
                                    ('cross','application',rectangle(400800,150500,401200,150700)),
                                    ('tiny','approved',rectangle(400200,150200,400200.5,150200.5))]:
                con.execute('''INSERT INTO map_features (run_id,feature_id,layer_id,rpc,map_stage,kind,tier_code,geom)
                    VALUES ('capture',?,'layer','RR',?,'tier','1B',ST_GeomFromWKB(?))''',[fid,stage,wgs(shape)])
            doc=transform.derive_tier_municipal(con)
            fs=doc['areas']['features']
            self.assertEqual(sorted((f['properties']['municipality'],f['properties']['map_stage']) for f in fs),
                             [('East','application'),('West','application'),('West','approved')])
            approved=next(f for f in fs if f['properties']['map_stage']=='approved')
            self.assertAlmostEqual(approved['properties']['area_before_closing_m2'],50000,places=2)
            self.assertTrue(any(x['operation']=='input' and x['area_m2']<1 for x in doc['audit']['removed_parts']))
            self.assertEqual(doc,transform.derive_tier_municipal(con))

    def test_offline_entrypoint_and_capture_only(self):
        with patch('sys.argv', ['transform.py', '--prepare', '--db', str(self.db), '--memberships', str(self.memberships)]), \
                patch('extract.capture', side_effect=AssertionError('unexpected download')), \
                patch('transform.load_snapshot', side_effect=AssertionError('unexpected load')):
            transform.main()
        with patch('sys.argv', ['extract.py']), patch('extract.capture', return_value='saved') as capture, \
                patch('transform.load_snapshot', side_effect=AssertionError('unexpected load')):
            extract.main()
            capture.assert_called_once()

    def test_mixed_export_generations_rejected_before_html_changes(self):
        self.export()
        build(self.output)
        before = (self.output / 'index.html').read_bytes()
        path = self.output / 'data/map.json'
        document = json.loads(path.read_text())
        for key in ('snapshot_id', 'captured_at', 'exported_at'):
            original = document[key]
            document[key] = 'different'
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, key):
                build(self.output)
            self.assertEqual((self.output / 'index.html').read_bytes(), before)
            document[key] = original

    def test_housing_export_generation_and_schema_checked_before_page_changes(self):
        self.export()
        build(self.output)
        before = (self.output / 'index.html').read_bytes()
        path = self.output / 'data/housing-growth.json'
        document = json.loads(path.read_text())
        original = dict(document)
        for key in ('snapshot_id', 'captured_at', 'exported_at'):
            document = {**original, key: 'different'}
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, key):
                build(self.output)
            self.assertEqual((self.output / 'index.html').read_bytes(), before)
        path.write_text(json.dumps({**original, 'schema_version': 99}))
        with self.assertRaisesRegex(ValueError, 'housing growth export schema'):
            build(self.output)
        self.assertEqual((self.output / 'index.html').read_bytes(), before)

    def test_housing_export_rejects_stale_preparation_without_publishing(self):
        self.export()
        previous = {p.name: p.read_bytes() for p in (self.output / 'data').iterdir()}
        path = self.root / 'housing-growth.json'
        document = json.loads(path.read_text())
        document['inputs_sha256'] = 'stale'
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, 'Stale'):
            export_all(self.db, self.output / 'data', self.memberships)
        self.assertEqual({p.name: p.read_bytes() for p in (self.output / 'data').iterdir()}, previous)

    def test_housing_source_urls_include_tier_and_boundary_inputs(self):
        with duckdb.connect(str(self.db)) as con:
            con.execute("INSERT INTO ingest_sources VALUES ('capture','flu-source','https://example.test/flu'),('capture','tier-source','https://example.test/tier'),('capture','boundary-source','https://example.test/towns')")
            con.execute("INSERT INTO current_layers VALUES ('capture','boundary-source','municipality_boundary')")
            document = {'snapshot_id': 'capture', 'inputs_sha256': 'test', 'rules': {'version': 1},
                        'sources': [{'source_id': 'flu-source'}],
                        'tier_sources': [{'source_id': 'tier-source'}], 'audit': {},
                        'categories': {'features': []}, 'blocks': {'features': []},
                        'tier_outside': {'features': []}, 'municipalities': [], 'reverse_diagnostics': []}
            with patch('transform.load_housing_growth', return_value=document):
                result = export_housing_growth(con)
            self.assertEqual(result['source_urls'], ['https://example.test/flu',
                'https://example.test/tier', 'https://example.test/towns'])

    def test_context_fragments_export_without_analytical_counts_or_property_changes(self):
        geometry = {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[1,1],[0,0]]]}
        properties = {'rpc': 'RR', 'flu_code': 'PGA', 'map_stage': 'approved',
                      'source_indices': [0], 'context_reason': 'outside_municipality_assignment',
                      'analytical_included': False, 'area_m2': 2400,
                      'geometry_sha256': 'original-projected-geometry'}
        fragment = {'type': 'Feature', 'id': 'fragment', 'geometry': geometry,
                    'properties': properties}
        document = {'snapshot_id': 'capture', 'inputs_sha256': 'test', 'rules': {'version': 2},
                    'sources': [{'source_id': None}], 'audit': {},
                    'categories': {'features': []}, 'blocks': {'features': []},
                    'tier_outside': {'features': []}, 'municipalities': [],
                    'reverse_diagnostics': [],
                    'context_fragments': {'type': 'FeatureCollection', 'features': [fragment]}}
        simplified = {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[0,1],[0,0]]]}
        with duckdb.connect(str(self.db)) as con, \
                patch('transform.load_housing_growth', return_value=document), \
                patch('analyze.simplify_display_geometry', return_value=(simplified,
                    {'retained_parts': [], 'feature_fallback': None})) as simplify:
            result = export_housing_growth(con)
        self.assertEqual(simplify.call_count, 1)
        self.assertEqual(result['context_fragments']['features'][0]['properties'], properties)
        self.assertEqual(result['context_fragments']['features'][0]['geometry'], simplified)
        self.assertEqual(result['summary']['blocks'], 0)
        self.assertEqual(result['summary']['context_fragments'], 1)
        self.assertEqual(sum(result['summary']['municipalities'].values()), 0)
        self.assertEqual(result['prepared_provenance']['rules_version'], 2)

    def test_coverage_parts_keep_shared_boundary_and_separate_area_metadata(self):
        geometry = {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[1,1],[0,0]]]}
        def feature(block, kind, portion):
            return {'type': 'Feature', 'id': f'{block}:{kind}', 'geometry': geometry,
                    'properties': {'block_id': block, 'coverage_kind': kind,
                                   'area_m2': 200, 'portion_area_m2': portion}}
        parts = [feature('split', 'covered', 80), feature('split', 'uncovered', 120),
                 feature('whole', 'covered', 200)]
        document = {'snapshot_id': 'capture', 'inputs_sha256': 'test', 'rules': {'version': 3},
                    'sources': [], 'audit': {}, 'categories': {'features': []},
                    'blocks': {'features': [feature('split', 'partial', 200), feature('whole', 'substantial', 200)]},
                    'tier_outside': {'features': []}, 'municipalities': [{'geoid': '001', 'status': 'some'},
                                                                         {'geoid': 'missing', 'status': 'no_housing'}],
                    'reverse_diagnostics': [], 'coverage_parts': {'type': 'FeatureCollection', 'features': parts}}
        simplified = {'type': 'Polygon', 'coordinates': [[[0,0],[1,0],[0,1],[0,0]]]}
        with duckdb.connect(str(self.db)) as con, \
                patch('transform.load_housing_growth', return_value=document), \
                patch('analyze.simplify_display_geometry', return_value=(simplified,
                    {'retained_parts': [], 'feature_fallback': None})) as simplify:
            con.execute('LOAD spatial')
            # A 1 km square municipality supplies the share-of-municipality denominator.
            con.execute('''UPDATE current_features SET geom=ST_Transform(ST_GeomFromText(
                'POLYGON((400000 150000,401000 150000,401000 151000,400000 151000,400000 150000))'),
                'EPSG:32145','EPSG:4326',always_xy:=true) WHERE geoid='001' ''')
            result = export_housing_growth(con)
        self.assertAlmostEqual(result['municipalities'][0]['municipality_area_m2'], 1_000_000, delta=1)
        self.assertIsNone(result['municipalities'][1]['municipality_area_m2'])
        self.assertEqual(simplify.call_count, 3)
        self.assertEqual([f['geometry'] for f in result['coverage_parts']['features'][:2]], [geometry, geometry])
        self.assertEqual(result['coverage_parts']['features'][2]['geometry'], simplified)
        self.assertEqual([f['properties']['portion_area_m2'] for f in parts], [80, 120, 200])
        self.assertTrue(all(f['properties']['area_m2']==200 for f in parts))
        self.assertEqual(result['summary']['blocks'], 2)
        self.assertEqual(result['summary']['coverage_parts'], 3)
        self.assertEqual(result['summary']['municipalities']['some'], 1)
        self.assertEqual(result['display_simplification']['retained_split_block_ids'], ['split'])

    def test_failed_serialization_keeps_complete_previous_exports(self):
        self.export()
        previous = {p.name: p.read_bytes() for p in (self.output / 'data').iterdir()}
        with patch.dict('analyze.EXPORTERS', {'broken': lambda con: {
                'title': 'Broken', 'source_view': 'interim_areas', 'bad': float('nan')}}):
            with self.assertRaises(ValueError):
                export_all(self.db, self.output / 'data', self.memberships)
        self.assertEqual({p.name: p.read_bytes() for p in (self.output / 'data').iterdir()}, previous)

    def test_failed_directory_replacement_restores_previous_exports(self):
        directory = self.root / 'exports'
        publish_json_directory(directory, {'old.json': {'old': True}})
        rename = Path.rename
        def fail_stage(path, target):
            if path.name == 'new':
                raise OSError('simulated publication failure')
            return rename(path, target)
        with patch.object(Path, 'rename', fail_stage):
            with self.assertRaisesRegex(OSError, 'simulated'):
                publish_json_directory(directory, {'new.json': {}})
        self.assertEqual(json.loads((directory / 'old.json').read_text()), {'old': True})

    def test_make_local_targets_never_capture_or_restore(self):
        for target in ('build', 'export', 'analyze', 'serve', 'rebuild'):
            result = subprocess.run(['make', '-n', target], text=True, capture_output=True, check=True)
            self.assertNotRegex(result.stdout, r'(?:extract|ingest)\.py|--snapshot|INSTALL spatial')
        result = subprocess.run(['make', 'transform'], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SNAPSHOT=', result.stderr)


if __name__ == '__main__':
    unittest.main()
