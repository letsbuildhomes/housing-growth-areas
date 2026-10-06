import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import transform


class PreparationForceTests(unittest.TestCase):
    def test_force_bypasses_spatial_fingerprint_shortcuts(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'saved.duckdb'
            db.touch()
            output = Path(folder) / 'prepared.json'
            stamp = {'schema_version': 1, 'snapshot_id': 'same'}
            for prepare, inputs, derive, document in (
                (transform.prepare_tier, 'tier_inputs', 'derive_tier_municipal',
                 {**stamp, 'areas': {'features': []}}),
                (transform.prepare_housing_growth, 'housing_inputs', 'derive_housing_growth',
                 {**stamp, 'blocks': {'features': []}}),
            ):
                output.write_text(json.dumps(stamp))
                with patch.object(transform.duckdb, 'connect'), \
                     patch.object(transform, inputs, return_value=(stamp, [], [])), \
                     patch.object(transform, derive, return_value=document) as compute:
                    prepare(db, output)
                    compute.assert_not_called()
                    prepare(db, output, force=True)
                    compute.assert_called_once()
                self.assertEqual(json.loads(output.read_text()), document)


class HousingGeometryTests(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        self.con.execute('LOAD spatial')
        self.con.execute("CREATE TABLE latest_ingest_run AS SELECT 'capture' run_id")
        self.con.execute('''CREATE TABLE map_features(run_id VARCHAR,feature_id VARCHAR,
            layer_id VARCHAR,source_id VARCHAR,source_oid VARCHAR,rpc VARCHAR,map_stage VARCHAR,
            submission_version VARCHAR,lurb_status VARCHAR,geom GEOMETRY,kind VARCHAR,
            tier_code VARCHAR,flu_code VARCHAR,date_lurb VARCHAR)''')
        self.con.execute('''CREATE TABLE current_features(feature_id VARCHAR,geoid VARCHAR,
            municipality VARCHAR,kind VARCHAR,geom GEOMETRY)''')
        self.con.execute('''INSERT INTO current_features SELECT 'town','001','Town',
            'municipality_boundary',ST_Transform(ST_GeomFromText(?),'EPSG:32145','EPSG:4326',always_xy:=true)''',
            [self.rectangle(400000,150000,403000,153000)])
        self.con.execute('CREATE VIEW municipal_boundaries AS SELECT * FROM current_features')
        self.con.execute("CREATE VIEW rpc_boundaries AS SELECT feature_id,'RR' rpc,geom FROM current_features")

    @staticmethod
    def rectangle(x,y,right,top):
        return f'POLYGON(({x} {y},{right} {y},{right} {top},{x} {top},{x} {y}))'

    def add(self,fid,shape,kind='flu',code='VA',stage='approved'):
        self.con.execute('''INSERT INTO map_features SELECT 'capture',?,'layer','source',?,
            'RR',?,'APP','APR',ST_Transform(ST_GeomFromText(?),'EPSG:32145','EPSG:4326',always_xy:=true),
            ?,?,?,NULL''',[fid,fid,stage,shape,kind,'1B' if kind=='tier' else None,code if kind=='flu' else None])

    def test_three_blocks_two_covered_and_reverse_outside(self):
        for i in range(3):
            shape=self.rectangle(400200+i*500,150200,400400+i*500,150400)
            self.add(f'h{i}',shape)
            if i<2:
                self.add(f't{i}',shape,'tier')
        self.add('extra',self.rectangle(402200,152200,402400,152400),'tier')
        doc=transform.derive_housing_growth(self.con)
        town=doc['municipalities'][0]
        self.assertEqual((town['status'],town['block_count'],town['substantial_count'],town['none_count']),('some',3,2,1))
        diagnostic=doc['reverse_diagnostics'][0]
        self.assertTrue(diagnostic['meaningful'])
        self.assertAlmostEqual(diagnostic['outside_fraction'],1/3,places=3)

    def test_category_union_and_road_gap_group_preserve_area(self):
        self.add('village',self.rectangle(400200,150200,400400,150400),code='VA')
        self.add('center',self.rectangle(400300,150200,400400,150400),code='VC')
        self.add('road-side',self.rectangle(400420,150200,400620,150400),code='PGA')
        self.add('tier',self.rectangle(400200,150200,400620,150400),'tier')
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(len(doc['categories']['features']),3)
        self.assertEqual(len(doc['blocks']['features']),1)
        self.assertEqual(doc['blocks']['features'][0]['geometry']['type'],'MultiPolygon')
        self.assertAlmostEqual(doc['blocks']['features'][0]['properties']['area_m2'],80000,delta=10)
        self.assertEqual(doc['municipalities'][0]['status'],'all')
        # Just beyond the grouping gap stays a separate block.
        start=400620+transform.config.HOUSING_RULES['grouping_gap_m']+10
        self.add('far',self.rectangle(start,150200,start+200,150400),code='VA')
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(len(doc['blocks']['features']),2)

    def test_nonhousing_new_stage_prevents_old_housing_fallback(self):
        self.add('old',self.rectangle(400200,150200,400400,150400),stage='pre_application')
        self.add('new',self.rectangle(400200,150200,400400,150400),code='RG')
        self.add('tier',self.rectangle(400200,150200,400400,150400),'tier')
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(doc['selected_stages'],{'RR':'approved'})
        self.assertEqual(doc['blocks']['features'],[])
        self.assertEqual(doc['municipalities'][0]['status'],'no_housing')

    def test_missing_housing_geometry_and_stage_mismatch_are_unknown(self):
        self.add('missing',None)
        self.add('tier',self.rectangle(400200,150200,400400,150400),'tier',stage='application')
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(doc['municipalities'][0]['status'],'unknown')
        self.assertEqual(doc['municipalities'][0]['comparison_status'],'incomplete_flu')
        self.con.execute("DELETE FROM map_features WHERE feature_id='missing'")
        self.add('h',self.rectangle(400200,150200,400400,150400))
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(doc['blocks']['features'][0]['properties']['coverage_status'],'unknown')
        self.assertEqual(doc['municipalities'][0]['comparison_status'],'stage_mismatch')
        self.assertEqual([p['properties']['coverage_kind'] for p in doc['coverage_parts']['features']],['unknown'])

    def test_tolerances_preserve_zero_overlap_and_material_partial(self):
        self.assertEqual(transform.housing_coverage(2,0),'none')
        self.assertEqual(transform.housing_coverage(1000000,999000),'substantial')
        self.assertEqual(transform.housing_coverage(1000000,975000),'partial')
        self.assertEqual(transform.housing_coverage(1000000,500000),'partial')

    def test_sidecar_rejects_changed_source_and_tier_rules(self):
        self.add('h',self.rectangle(400200,150200,400400,150400))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'housing.json'
            transform.write_json(path,transform.derive_housing_growth(self.con))
            self.assertEqual(transform.load_housing_growth(self.con,path)['snapshot_id'],'capture')
            with patch.dict(transform.config.TIER_RULES,version=999):
                with self.assertRaisesRegex(ValueError,'Stale'):
                    transform.load_housing_growth(self.con,path)
            self.con.execute("UPDATE map_features SET flu_code='RG'")
            with self.assertRaisesRegex(ValueError,'Stale'):
                transform.load_housing_growth(self.con,path)

    def test_nonpolygon_source_is_audited_and_cannot_imply_no_housing(self):
        self.add('line','LINESTRING(400200 150200,400400 150400)')
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(doc['municipalities'][0]['status'],'unknown')
        self.assertEqual(doc['audit']['unassigned_parts'][0]['reason'],'no polygon geometry after repair')

    def test_boundary_components_are_context_and_tier_comparison_is_clipped(self):
        self.add('accepted',self.rectangle(400200,150200,400400,150400))
        self.add('boundary',self.rectangle(400001,150600,400051,150800))
        self.add('tier',self.rectangle(400001,150200,400401,150800),'tier')
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(doc['municipalities'][0]['status'],'all')
        self.assertEqual(len(doc['blocks']['features']),1)
        context=doc['context_fragments']['features'][0]
        self.assertFalse(context['properties']['analytical_included'])
        self.assertEqual(context['properties']['context_reason'],'outside_municipality_assignment')
        self.assertAlmostEqual(context['properties']['area_m2'],10000,delta=0.01)
        self.assertEqual(doc['audit']['unassigned_parts'][0]['analytical_exclusion'],'outside_municipality_assignment')
        reverse=doc['reverse_diagnostics'][0]
        self.assertAlmostEqual(reverse['display_tier_area_m2']-reverse['tier_area_m2'],10000,delta=1)
        self.assertAlmostEqual(reverse['analytical_excluded_m2'],10000,delta=1)
        self.assertEqual(doc['blocks']['features'][0]['properties']['coverage_status'],'substantial')

    def test_isolated_boundary_components_do_not_create_unknown_or_membership(self):
        boundary=self.rectangle(400001,150600,400051,150800)
        self.add('isolated',boundary)
        self.add('tier-isolated',boundary,'tier')
        self.add('tier-accepted',self.rectangle(400200,150200,400400,150400),'tier')
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(doc['municipalities'][0]['status'],'no_housing')
        self.assertEqual(doc['blocks']['features'],[])
        self.assertEqual(len(doc['context_fragments']['features']),1)
        self.assertEqual(len(doc['boundary_context']['tier_adjustments']),1)
        self.assertEqual(doc['uncertainty']['incomplete_tier_municipalities'],[])

    def test_context_mask_never_erases_an_accepted_housing_component(self):
        accepted=self.rectangle(400001,150200,400401,150800)
        self.add('accepted',accepted)
        self.add('boundary',self.rectangle(400001,150600,400051,150800))
        self.add('tier',accepted,'tier')
        doc=transform.derive_housing_growth(self.con)
        self.assertEqual(len(doc['context_fragments']['features']),1)
        self.assertEqual(doc['municipalities'][0]['status'],'all')
        self.assertAlmostEqual(doc['reverse_diagnostics'][0]['analytical_excluded_m2'],0,delta=1)

    def test_coverage_portions_partition_a_partially_covered_block(self):
        self.add('housing',self.rectangle(400200,150200,400400,150400))
        self.add('tier',self.rectangle(400100,150100,400300,150500),'tier')
        doc=transform.derive_housing_growth(self.con)
        block=doc['blocks']['features'][0]
        parts=doc['coverage_parts']['features']
        self.assertEqual({p['properties']['coverage_kind'] for p in parts},{'covered','uncovered'})
        self.assertEqual(doc['municipalities'][0]['status'],'some')
        self.assertAlmostEqual(sum(p['properties']['portion_area_m2'] for p in parts),block['properties']['area_m2'],delta=0.0001)
        for p in parts:
            self.assertEqual(p['properties']['block_id'],block['id'])
            self.assertEqual(p['properties']['source_indices'],block['properties']['source_indices'])
            self.assertEqual(p['properties']['tier_source_indices'],block['properties']['tier_source_indices'])
        green=next(p for p in parts if p['properties']['coverage_kind']=='covered')
        red=next(p for p in parts if p['properties']['coverage_kind']=='uncovered')
        overlap,remainder,green_outside=self.con.execute('''SELECT ST_Area(ST_Intersection(c,u)),
            ST_Area(ST_SymDifference(ST_Union(c,u),b)),ST_Area(ST_Difference(c,b)) FROM
            (SELECT ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326','EPSG:32145',always_xy:=true) c,
                    ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326','EPSG:32145',always_xy:=true) u,
                    ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326','EPSG:32145',always_xy:=true) b)''',
            [json.dumps(green['geometry']),json.dumps(red['geometry']),json.dumps(block['geometry'])]).fetchone()
        self.assertLess(overlap,0.0001)
        # WGS84 straight display segments become curved under projection; newly
        # inserted split vertices can change the projected approximation slightly.
        self.assertLess(remainder,1)
        self.assertLess(green_outside,1)
        # Browser portions share their split edge exactly: no overlap and no seam.
        wgs_overlap,pieces,holes,valid=self.con.execute('''SELECT ST_Area(ST_Intersection(c,u)),
            ST_NumGeometries(ST_Union(c,u)),ST_NumInteriorRings(ST_Union(c,u)),
            ST_IsValid(c) AND ST_IsValid(u) FROM
            (SELECT ST_GeomFromGeoJSON(?) c,ST_GeomFromGeoJSON(?) u)''',
            [json.dumps(green['geometry']),json.dumps(red['geometry'])]).fetchone()
        self.assertTrue(valid)
        self.assertLess(wgs_overlap,1e-14)
        self.assertEqual((pieces,holes),(1,0))

    def coverage(self,tier_right):
        self.add('housing',self.rectangle(400200,150200,400400,150400))
        self.add('tier',self.rectangle(400200,150200,tier_right,150400),'tier')
        doc=transform.derive_housing_growth(self.con)
        parts={p['properties']['coverage_kind']:p['properties'] for p in doc['coverage_parts']['features']}
        return doc['blocks']['features'][0]['properties'],parts

    def test_hairline_uncovered_strip_joins_covered_portion(self):
        block,parts=self.coverage(400399)
        self.assertEqual(set(parts),{'covered'})
        self.assertAlmostEqual(block['covered_m2'],40000,delta=0.01)
        self.assertAlmostEqual(block['exact_covered_m2'],39800,delta=0.01)
        self.assertEqual(block['coverage_status'],'substantial')

    def test_hairline_covered_strip_joins_uncovered_portion(self):
        block,parts=self.coverage(400201)
        self.assertEqual(set(parts),{'uncovered'})
        self.assertEqual(block['covered_m2'],0)
        self.assertAlmostEqual(block['exact_covered_m2'],200,delta=0.01)
        self.assertEqual(block['coverage_status'],'none')

    def test_uncovered_strip_wider_than_sliver_rule_remains_visible(self):
        block,parts=self.coverage(400390)
        self.assertEqual(set(parts),{'covered','uncovered'})
        self.assertAlmostEqual(parts['uncovered']['portion_area_m2'],2000,delta=0.01)
        self.assertEqual(block['covered_m2'],block['exact_covered_m2'])


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
