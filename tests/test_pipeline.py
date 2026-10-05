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
from analyze import export_all
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
            con.execute('CREATE TABLE ingest_sources (run_id VARCHAR, source_id VARCHAR, url VARCHAR)')
            con.execute('CREATE TABLE current_layers (run_id VARCHAR, source_id VARCHAR, kind VARCHAR)')
            con.execute('''CREATE TABLE map_features (run_id VARCHAR, feature_id VARCHAR,
                source_id VARCHAR, source_oid VARCHAR, layer_id VARCHAR, rpc VARCHAR,
                name VARCHAR, map_stage VARCHAR, submission_version VARCHAR,
                lurb_status VARCHAR, geometry_valid BOOLEAN, geom GEOMETRY,
                kind VARCHAR, tier_code VARCHAR)''')
            transform.create_tier1b_working_view(con)

    def export(self):
        prepare(self.db, self.memberships)
        transform.prepare_tier(self.db)
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
