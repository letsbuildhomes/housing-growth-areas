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

    def export(self):
        prepare(self.db, self.memberships)
        export_all(self.db, self.output / 'data', self.memberships)

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
