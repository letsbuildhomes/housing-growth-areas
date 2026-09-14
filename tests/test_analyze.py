import json
from pathlib import Path
import re
import tempfile
import unittest
import duckdb

from analyze import build
from analyze import group_areas, export_all, export_map
from transform import derive_memberships


def area(name, category, municipality='EXAMPLE TOWN', **kwargs):
    return {'feature_id': name, 'name': name, 'category': category,
            'municipality': municipality, 'exemption_type': None,
            'likely_eligible': True, 'zoning_bylaws': None,
            'drinking_water': False, 'sewer_wastewater': True, 'adequate_soils': True,
            **kwargs}


class DashboardTests(unittest.TestCase):
    def test_story_towns_use_membership_despite_neighboring_geometry(self):
        with duckdb.connect(':memory:') as con:
            con.execute('LOAD spatial')
            con.execute('CREATE TABLE current_features (feature_id VARCHAR, name VARCHAR, municipality VARCHAR, geoid VARCHAR, kind VARCHAR, rpc VARCHAR, geom GEOMETRY)')
            con.execute('CREATE TABLE interim_areas (feature_id VARCHAR, name VARCHAR, municipality VARCHAR, category VARCHAR, likely_eligible BOOLEAN, geom GEOMETRY)')
            con.execute('CREATE TABLE ingest_sources (run_id VARCHAR, source_id VARCHAR, url VARCHAR)')
            con.execute('CREATE TABLE current_layers (run_id VARCHAR, source_id VARCHAR, kind VARCHAR)')
            for index in range(4):
                x = index * 10
                con.execute("INSERT INTO current_features VALUES (?, ?, ?, ?, 'municipality_boundary', NULL, ST_GeomFromText(?))",
                            [str(index), str(index), str(index), str(index), f'POLYGON(({x} 0,{x+4} 0,{x+4} 4,{x} 4,{x} 0))'])
            # Geometry in a neighboring town must not confer membership there.
            for index, eligible in enumerate([True, False, None]):
                x = (index + 1) * 10 + 1
                con.execute("INSERT INTO interim_areas VALUES (?, 'Area', ?, 'village_center_buffer', ?, ST_GeomFromText(?))",
                            [str(index), str(index), eligible, f'POLYGON(({x} 1,{x+1} 1,{x+1} 2,{x} 2,{x} 1))'])
            from transform import inputs
            result = export_map(con, derive_memberships(*inputs(con)))
            flags = [(f['properties']['has_designated_area'], f['properties']['has_likely_eligible']) for f in result['towns']['features']]
            self.assertEqual(flags, [(True, True), (True, False), (True, False), (False, False)])
            self.assertEqual(result['summary']['towns_with_designated_area'], 3)
            self.assertEqual(result['summary']['towns_with_likely_eligible_area'], 1)
            self.assertIsNone(result['areas']['features'][2]['properties']['likely_eligible'])

    def test_group_and_sort_without_dropping_areas(self):
        rows = [area('Alpha growth', 'town_growth_development'),
                area('Z village', 'village_center_buffer'),
                area('Z downtown', 'downtown_district'),
                area('A downtown', 'downtown_district', ' Example   Town '),
                area('A village', 'village_center_buffer'),
                area('Other', 'downtown_district', 'ALBANY')]
        groups = group_areas(rows)
        self.assertEqual([g['municipality'] for g in groups], ['ALBANY', 'EXAMPLE TOWN'])
        self.assertEqual([a['name'] for a in groups[1]['areas']],
                         ['A downtown', 'Z downtown', 'A village', 'Z village', 'Alpha growth'])
        self.assertEqual(sum(len(g['areas']) for g in groups), len(rows))
        self.assertIsNone(groups[1]['areas'][0]['zoning_bylaws'])
        self.assertIs(groups[1]['areas'][0]['drinking_water'], False)
        self.assertEqual(rows[3]['municipality'], ' Example   Town ')

    def test_unknown_municipality_retains_record(self):
        groups = group_areas([area('Test', 'downtown_district', None)])
        self.assertEqual(groups[0]['municipality'], 'Unknown municipality')

    def test_new_category_requires_explicit_order(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            group_areas([area('Test', 'unexpected')])

    def test_missing_database_never_creates_or_downloads_one(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / 'missing.duckdb'
            with self.assertRaisesRegex(SystemExit, 'Restore'):
                export_all(db, Path(temp) / 'output')
            self.assertFalse(db.exists())
            self.assertFalse((Path(temp) / 'output').exists())

    def test_standalone_payload_cannot_inject_html(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / 'data').mkdir()
            common = {'snapshot_id': 'test', 'captured_at': '2026-09-08', 'exported_at': '2026-09-13'}
            (output / 'data' / 'manifest.json').write_text(json.dumps(common))
            payload = {**common, 'schema_version': 1, 'name': '</script><img src=x onerror=alert(1)>&'}
            (output / 'data' / 'interim-areas.json').write_text(json.dumps(payload))
            (output / 'data' / 'map.json').write_text(json.dumps({
                **common, 'schema_version': 2, 'areas': {'type': 'FeatureCollection', 'features': []},
                'towns': {'type': 'FeatureCollection', 'features': []},
                'rpcs': {'type': 'FeatureCollection', 'features': []},
            }))
            build(output)
            html = (output / 'index.html').read_text()
            embedded = re.search(r'<script type="application/json" id="interim-data">(.*?)</script>', html, re.S)[1]
            self.assertEqual(json.loads(embedded), payload)
            self.assertNotIn('<img src=x', html)
            self.assertNotIn('{{DATA}}', html)
            self.assertNotRegex(html, r'<script[^>]+src=|<link[^>]+href=')

    def test_shared_membership_preserves_one_area_and_raw_label_without_geometry(self):
        source = area('shared', 'village_center_buffer', ' JERICHO\\UNDERHILL ')
        towns = [{'municipality': name, 'geoid': name} for name in ('Jericho', 'Underhill')]
        result = derive_memberships([source], towns)
        self.assertEqual({r['municipality'] for r in result}, {'Jericho', 'Underhill'})
        self.assertEqual({r['feature_id'] for r in result}, {'shared'})
        self.assertEqual(source['municipality'], ' JERICHO\\UNDERHILL ')

    def test_approved_locality_and_feature_overrides_fail_closed(self):
        towns = [{'municipality': name, 'geoid': name} for name in ('Plymouth', 'Rutland City')]
        source = [area('tyson', 'village_center_buffer', 'TYSON'),
                  area('95d37a2dfaaeb934:21', 'town_growth_development', 'Rutland')]
        self.assertEqual([m['municipality'] for m in derive_memberships(source, towns)],
                         ['Plymouth', 'Rutland City'])
        for label in ('Rutland', 'Unreviewed label', None):
            with self.assertRaisesRegex(ValueError, 'Review municipality membership'):
                derive_memberships([area('new', 'town_growth_development', label)], towns)
        with self.assertRaisesRegex(ValueError, 'Missing approved municipality target'):
            derive_memberships([source[0]], towns[1:])
        with self.assertRaisesRegex(ValueError, 'Ambiguous/missing'):
            derive_memberships([], towns + towns)


if __name__ == '__main__':
    unittest.main()
