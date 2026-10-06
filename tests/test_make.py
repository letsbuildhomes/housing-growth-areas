"""Exercise Make scheduling with disposable outputs, without research data."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(shutil.which('make'), 'GNU Make required')
class MakeBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'Makefile', self.root / 'Makefile')
        for name in ('transform.py', 'config.py', 'arcgis.py', 'analyze.py',
                     'pyproject.toml', 'uv.lock', 'data/act181_ingest.duckdb', 'web/dashboard.css'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('fixture')
        self.stub = self.root / 'runner.py'
        self.stub.write_text(r"""import pathlib, sys
root = pathlib.Path('.')
with open('calls', 'a') as f: f.write(' '.join(sys.argv[1:]) + '\n')
if sys.argv[1] == 'transform.py':
    assert '--force' in sys.argv
    paths = ['data/municipality-memberships.json', 'data/tier1b-municipal.json', 'data/housing-growth.json']
    # Existing identical content deliberately keeps its old timestamp.
    for name in paths:
        p = root / name
        if not p.exists(): p.write_text('prepared')
    if (root / 'fail-prepare').exists(): sys.exit(1)
elif '--export' in sys.argv:
    if (root / 'fail-export').exists(): sys.exit(1)
    for name in ['manifest', 'interim-areas', 'map', 'tier1b', 'housing-growth']:
        p = root / ('out/dashboard/data/' + name + '.json')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('exported')
else:
    p = root / 'out/dashboard/index.html'
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('page')
""")

    def make(self, *goals, succeeds=True):
        result = subprocess.run(['make', '--no-print-directory', '-j4',
                                 'UV=' + sys.executable + ' ' + str(self.stub), *goals],
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, succeeds, result.stdout + result.stderr)
        calls = self.root / 'calls'
        lines = calls.read_text().splitlines() if calls.exists() else []
        calls.unlink(missing_ok=True)
        return lines

    def changed(self, name):
        # Newer than the current outputs, without sleeps or future timestamps.
        (self.root / name).touch()

    def test_incremental_and_missing_group_outputs(self):
        self.assertEqual(len(self.make('build')), 3)
        self.assertEqual(self.make('build', 'prepare', 'export'), [])
        self.changed('web/dashboard.css')
        self.assertEqual(self.make('build'), ['analyze.py --page'])
        for name in ('transform.py', 'config.py', 'arcgis.py', 'uv.lock', 'pyproject.toml',
                     'data/act181_ingest.duckdb', 'Makefile'):
            self.changed(name)
            self.assertEqual(len(self.make('build')), 3, name)
            self.assertEqual(self.make('build'), [], name)
        self.changed('analyze.py')
        self.assertEqual(self.make('build'), ['analyze.py --export', 'analyze.py --page'])
        (self.root / 'data/tier1b-municipal.json').unlink()
        self.assertEqual(len(self.make('build', 'export', 'prepare')), 3)
        (self.root / 'out/dashboard/data/map.json').unlink()
        self.assertEqual(self.make('build', 'export'), ['analyze.py --export', 'analyze.py --page'])
        self.assertEqual(len(self.make('-B', 'build')), 3)

    def test_page_only_and_failed_export(self):
        self.assertEqual(self.make('page', succeeds=False), [])

        self.make('build')
        self.changed('config.py')
        self.assertEqual(self.make('page'), ['analyze.py --page'])
        original = (self.root / 'out/dashboard/data/map.json').read_bytes()
        (self.root / 'fail-export').touch()
        self.assertEqual(len(self.make('export', succeeds=False)), 2)
        self.assertEqual((self.root / 'out/dashboard/data/map.json').read_bytes(), original)
        (self.root / 'out/dashboard/data/map.json').unlink()
        self.assertEqual(self.make('page', succeeds=False), [])

    def test_failed_preparation_retries_missing_sibling(self):
        self.make('build')
        missing = self.root / 'data/tier1b-municipal.json'
        missing.unlink()
        (self.root / 'fail-prepare').touch()
        self.assertEqual(self.make('prepare', succeeds=False), ['transform.py --prepare --force'])
        self.assertFalse(missing.exists())
        (self.root / 'fail-prepare').unlink()
        self.assertEqual(self.make('prepare'), ['transform.py --prepare --force'])
