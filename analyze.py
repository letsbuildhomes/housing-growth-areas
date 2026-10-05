"""Report on prepared research data and build the standalone dashboard."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

import duckdb
from config import ROOT, DB_PATH, DASHBOARD_DIR, EXPORT_DIR, MEMBERSHIP_PATH, MEMBERSHIP_VERSION, HOUSING_RULES
from transform import load_prepared, MEMBERSHIP_BASIS


# Read-only dataset queries

CATEGORIES = {
    'downtown_district': 'Downtown district',
    'village_center_buffer': 'Village center + buffer',
    'town_growth_development': 'Town/growth center or development area',
}
CATEGORY_ORDER = {key: i for i, key in enumerate(CATEGORIES)}
AREA_FIELDS = [
    'feature_id', 'source_oid', 'municipality', 'name', 'category', 'exemption_type',
    'likely_eligible', 'zoning_bylaws', 'drinking_water', 'sewer_wastewater', 'adequate_soils',
]


def group_areas(areas):
    """Keep every source area; group case-insensitively without assigning towns."""
    grouped = {}
    for original in areas:
        area = dict(original)
        label = ' '.join((area['municipality'] or '').split()) or 'Unknown municipality'
        key = label.casefold()
        group = grouped.setdefault(key, {'municipality': label, 'areas': []})
        if area['category'] not in CATEGORY_ORDER:
            raise ValueError(f"Unsupported interim category: {area['category']}")
        area['category_label'] = CATEGORIES[area['category']]
        area['name'] = area['name'] or area['exemption_type'] or area['category_label']
        group['areas'].append(area)
    for group in grouped.values():
        group['areas'].sort(key=lambda a: (
            CATEGORY_ORDER[a['category']], a['name'].casefold(),
            (a['exemption_type'] or '').casefold(), a['feature_id'],
        ))
    return [grouped[key] for key in sorted(grouped)]


def export_interim(con):
    rows = con.execute('SELECT ' + ', '.join(AREA_FIELDS) + ' FROM interim_areas').fetchall()
    areas = [dict(zip(AREA_FIELDS, row)) for row in rows]
    if len({a['feature_id'] for a in areas}) != len(areas):
        raise ValueError('Interim view contains duplicate source features; review layer membership.')
    groups = group_areas(areas)
    sources = con.execute('''SELECT DISTINCT s.url FROM ingest_sources s
        JOIN current_layers l USING (run_id, source_id)
        WHERE l.kind = 'interim' ORDER BY s.url''').fetchall()
    return {
        'title': 'Interim Act 250 exemption areas',
        'source_view': 'interim_areas',
        'source_urls': [row[0] for row in sources],
        'sort': ['municipality A–Z', 'downtown_district', 'village_center_buffer',
                 'town_growth_development', 'area name A–Z within category'],
        'summary': {
            'areas': len(areas), 'municipalities': len(groups),
            'likely_eligible': sum(a['likely_eligible'] is True for a in areas),
            'likely_not_eligible': sum(a['likely_eligible'] is False for a in areas),
            'eligibility_unknown': sum(a['likely_eligible'] is None for a in areas),
        },
        'municipalities': groups,
    }


def geojson_feature(row, fields):
    properties = dict(zip(fields, row[:-1]))
    geometry = json.loads(row[-1]) if row[-1] is not None else None
    return {'type': 'Feature', 'id': properties.get('feature_id'),
            'properties': properties, 'geometry': geometry}


def export_map(con, memberships=None):
    """Export only the geometries and attributes needed by the offline map."""
    area_fields = ['feature_id', 'name', 'municipality', 'category', 'likely_eligible']
    area_rows = con.execute('''SELECT feature_id, name, municipality, category,
                                      likely_eligible, ST_AsGeoJSON(geom)
                               FROM interim_areas
                               ORDER BY feature_id''').fetchall()
    town_fields = ['feature_id', 'name', 'municipality', 'geoid']
    town_rows = con.execute('''SELECT t.feature_id, t.name, t.municipality, t.geoid,
                                     ST_AsGeoJSON(t.geom)
                              FROM current_features t
                              WHERE t.kind = 'municipality_boundary'
                              ORDER BY t.municipality, t.feature_id''').fetchall()
    rpc_fields = ['feature_id', 'rpc', 'name']
    rpc_rows = con.execute('''SELECT feature_id, rpc, name, ST_AsGeoJSON(geom)
                              FROM current_features
                              WHERE kind = 'rpc_boundary'
                              ORDER BY name, feature_id''').fetchall()
    sources = con.execute('''SELECT DISTINCT s.url
        FROM ingest_sources s JOIN current_layers l USING (run_id, source_id)
        WHERE l.kind IN ('interim', 'municipality_boundary', 'rpc_boundary')
        ORDER BY s.url''').fetchall()
    areas = [geojson_feature(row, area_fields) for row in area_rows]
    towns = [geojson_feature(row, town_fields) for row in town_rows]
    focus_rpcs = {}
    if town_rows and rpc_rows:
        for town_id, rpc in con.execute('''
            SELECT t.feature_id, r.rpc FROM current_features t
            JOIN current_features r ON ST_Covers(r.geom, ST_PointOnSurface(t.geom))
            WHERE t.kind = 'municipality_boundary' AND r.kind = 'rpc_boundary'
        ''').fetchall():
            if town_id in focus_rpcs:
                raise ValueError(f'Ambiguous RPC focus membership: {town_id}')
            focus_rpcs[town_id] = rpc
        if len(focus_rpcs) != len(towns):
            raise ValueError('Missing RPC focus membership for municipality boundary')
    if memberships is None:
        memberships = load_prepared(con)
    eligible_ids = {a['properties']['feature_id'] for a in areas
                    if a['properties']['likely_eligible'] is True}
    designated = {m['municipality_geoid'] for m in memberships}
    eligible = {m['municipality_geoid'] for m in memberships if m['feature_id'] in eligible_ids}
    for town in towns:
        props = town['properties']
        props['focus_rpc'] = focus_rpcs.get(props['feature_id'])
        props['has_designated_area'] = props['geoid'] in designated
        props['has_likely_eligible'] = props['geoid'] in eligible
    rpcs = [geojson_feature(row, rpc_fields) for row in rpc_rows]
    return {
        'title': 'Interim areas and Vermont boundary reference layers',
        'schema_version': 2,
        'membership_version': MEMBERSHIP_VERSION,
        'membership_basis': MEMBERSHIP_BASIS,
        'memberships': memberships,
        'source_view': 'interim_areas + municipal_boundaries + rpc_boundaries',
        'source_urls': [row[0] for row in sources],
        'summary': {'areas': len(areas), 'municipalities': len(towns), 'rpcs': len(rpcs),
                    'towns_with_designated_area': sum(
                        f['properties']['has_designated_area'] for f in towns),
                    'towns_with_likely_eligible_area': sum(
                        f['properties']['has_likely_eligible'] for f in towns)},
        'areas': {'type': 'FeatureCollection', 'features': areas},
        'towns': {'type': 'FeatureCollection', 'features': towns},
        'rpcs': {'type': 'FeatureCollection', 'features': rpcs},
    }


# Add future datasets here. Each exporter receives the same read-only database
# connection/snapshot and returns JSON-serializable content.
DISPLAY_SIMPLIFICATION = {'version': 1, 'crs': 'EPSG:32145', 'tolerance_m': 0.5,
                          'max_changed_fraction': 0.05, 'boundary_slack_m': 0.001,
                          'buffer_segments': 64, 'protect_neighbors': False}


def simplify_display_geometry(con, geometry):
    """Simplify a temporary display copy; reject unsafe parts and recombinations."""
    rules = DISPLAY_SIMPLIFICATION
    audit = {'retained_parts': [], 'feature_fallback': None}
    try:
        original = con.execute("SELECT ST_AsWKB(ST_Transform(ST_GeomFromGeoJSON(?),"
                               "'EPSG:4326','EPSG:32145',always_xy:=true))",
                               [json.dumps(geometry)]).fetchone()[0]
        parts = con.execute('SELECT ST_AsWKB(p.geom) FROM unnest(ST_Dump(ST_GeomFromWKB(?))) t(p) ORDER BY p.path',
                            [original]).fetchall()
        chosen = []
        for index, (part,) in enumerate(parts):
            try:
                row = con.execute('''WITH a AS (SELECT ST_GeomFromWKB(?) g),
                    b AS (SELECT g,ST_SimplifyPreserveTopology(g,?) s FROM a)
                    SELECT ST_AsWKB(s), ST_IsValid(s) AND NOT ST_IsEmpty(s)
                      AND ST_NumInteriorRings(g)=ST_NumInteriorRings(s)
                      AND ST_Area(ST_SymDifference(g,s))<=?*ST_Area(g)
                      AND ST_Covers(ST_Buffer(ST_Boundary(g),?,64),ST_Boundary(s))
                      AND ST_Covers(ST_Buffer(ST_Boundary(s),?,64),ST_Boundary(g)) FROM b''',
                    [part, rules['tolerance_m'], rules['max_changed_fraction'],
                     rules['tolerance_m']+rules['boundary_slack_m'],
                     rules['tolerance_m']+rules['boundary_slack_m']]).fetchone()
                if row[1]:
                    chosen.append(row[0])
                    continue
                reason = 'geometry_checks'
            except duckdb.Error:
                reason = 'operation_error'
            chosen.append(part)
            audit['retained_parts'].append({'part': index, 'reason': reason})
        encoded = con.execute('''SELECT ST_AsGeoJSON(ST_Transform(
            ST_Multi(ST_Collect(list(ST_GeomFromWKB(w) ORDER BY i))),
            'EPSG:32145','EPSG:4326',always_xy:=true))
            FROM unnest(?::BLOB[]) WITH ORDINALITY t(w,i)''', [chosen]).fetchone()[0]
        # Check the actual serialized geometry, including round-trip topology.
        valid, count, holes = con.execute('''WITH a AS (SELECT ST_GeomFromGeoJSON(?) g)
            SELECT ST_IsValid(g) AND NOT ST_IsEmpty(g),len(ST_Dump(g)),
            (SELECT sum(ST_NumInteriorRings(p.geom)) FROM unnest(ST_Dump(g)) t(p)) FROM a''',
            [encoded]).fetchone()
        original_holes = con.execute('SELECT sum(ST_NumInteriorRings(p.geom)) FROM unnest(ST_Dump(ST_GeomFromWKB(?))) t(p)',
                                     [original]).fetchone()[0]
        if valid and count == len(parts) and holes == original_holes:
            return json.loads(encoded), audit
        audit['feature_fallback'] = 'recombined_geometry_checks'
    except duckdb.Error:
        audit['feature_fallback'] = 'operation_error'
    return geometry, audit


def export_tier1b(con):
    """Publish the selected municipal stages from the validated prepared sidecar."""
    from transform import tier_inputs
    db_file = con.execute("SELECT path FROM duckdb_databases() WHERE database_name=current_database()").fetchone()[0]
    path = Path(db_file).parent / 'tier1b-municipal.json'
    if not path.is_file():
        raise ValueError('Missing municipal Tier 1B preparation; run make prepare.')
    document = json.loads(path.read_text())
    stamp, _, _ = tier_inputs(con)
    if any(document.get(k) != v for k,v in stamp.items()):
        raise ValueError('Stale municipal Tier 1B preparation; run make prepare.')
    features = [f for f in document['areas']['features']
                if document['selected_stages'][f['properties']['rpc']] == f['properties']['map_stage']]
    simplification_audit = {}
    with duckdb.connect(':memory:') as display_con:
        display_con.execute('LOAD spatial')
        for feature in features:
            feature['geometry'], audit = simplify_display_geometry(display_con, feature['geometry'])
            if audit['retained_parts'] or audit['feature_fallback']:
                simplification_audit[feature['id']] = audit
    source_indices = sorted({i for f in features for i in f['properties']['source_indices']})
    source_ids = sorted({document['audit']['sources'][i]['source_id'] for i in source_indices})
    sources = con.execute('''SELECT DISTINCT url FROM ingest_sources WHERE run_id=?
        AND source_id IN (SELECT unnest(?::VARCHAR[])) ORDER BY url''',
        [stamp['snapshot_id'], source_ids]).fetchall()
    dates = dict(con.execute('''SELECT feature_id, date_lurb FROM map_features
        WHERE kind='tier' AND tier_code='1B' ORDER BY feature_id, date_lurb''').fetchall())
    return {'title': 'Tier 1B boundaries', 'schema_version': 3,
            'source_view': 'prepared municipal Tier 1B; furthest stage per RPC',
            'source_urls': [r[0] for r in sources], 'processing_rules': document['rules'],
            'display_simplification': {'rules': DISPLAY_SIMPLIFICATION,
                                      'engine': 'DuckDB ' + duckdb.__version__,
                                      'fallbacks': simplification_audit},
            'source_records': {str(i): {**document['audit']['sources'][i],
                'date_lurb': dates.get(document['audit']['sources'][i]['feature_id'])}
                for i in source_indices},
            'summary': {stage: sum(f['properties']['map_stage']==stage for f in features)
                        for stage in ('pre_application','application','approved')},
            'areas': {'type':'FeatureCollection','features':features}}


def export_housing_growth(con):
    """Publish validated analytical geometry separately from interim table data."""
    from transform import load_housing_growth
    db_file = con.execute("SELECT path FROM duckdb_databases() WHERE database_name=current_database()").fetchone()[0]
    document = load_housing_growth(con, Path(db_file).parent / 'housing-growth.json')
    audit = document.pop('audit')
    # Keep the full projected-WKB repair/assignment audit in the saved sidecar.
    # Web consumers need lineage and counts, not duplicate detailed geometry.
    document['audit_summary'] = {
        key: len(value) for key, value in audit.items()
        if isinstance(value, list) and key != 'sources'
    }
    document['prepared_provenance'] = {
        'sidecar': 'data/housing-growth.json',
        'inputs_sha256': document['inputs_sha256'],
        'rules_version': document['rules']['version'],
    }
    # Municipal area in the analysis CRS gives hover labels a share-of-municipality denominator.
    con.execute('LOAD spatial')
    town_areas = dict(con.execute('''SELECT geoid,ST_Area(ST_Transform(geom,'EPSG:4326',?,always_xy:=true))
        FROM current_features WHERE kind='municipality_boundary' AND geom IS NOT NULL''',
        [HOUSING_RULES['crs']]).fetchall())
    for town in document['municipalities']:
        town['municipality_area_m2'] = town_areas.get(town['geoid'])
    document['summary'] = {
        'blocks': len(document['blocks']['features']),
        'municipalities': {status: sum(town['status'] == status for town in document['municipalities'])
                           for status in ('all', 'some', 'none', 'no_housing', 'unknown')},
        'meaningful_tier_outside': sum(item['meaningful'] for item in document['reverse_diagnostics']),
        'context_fragments': len(document.get('context_fragments', {}).get('features', [])),
        'coverage_parts': len(document.get('coverage_parts', {}).get('features', [])),
    }
    source_ids = sorted({source['source_id'] for source in
                         document['sources'] + document.get('tier_sources', [])
                         if source.get('source_id') is not None})
    urls = con.execute('''SELECT DISTINCT url FROM ingest_sources WHERE run_id=?
        AND (source_id IN (SELECT unnest(?::VARCHAR[])) OR source_id IN
             (SELECT source_id FROM current_layers
              WHERE kind IN ('municipality_boundary','rpc_boundary')))
        ORDER BY url''',
        [document['snapshot_id'], source_ids]).fetchall()
    fallbacks = {}
    part_counts = {}
    for feature in document.get('coverage_parts', {}).get('features', []):
        block_id = feature['properties']['block_id']
        part_counts[block_id] = part_counts.get(block_id, 0) + 1
    retained_split_blocks = sorted(block_id for block_id, count in part_counts.items() if count > 1)
    with duckdb.connect(':memory:') as display_con:
        display_con.execute('LOAD spatial')
        for name in ('categories', 'blocks', 'coverage_parts', 'tier_outside', 'context_fragments'):
            for feature in document.get(name, {}).get('features', []):
                # Complementary pieces share a computed boundary. Retain both
                # original shapes rather than simplifying that edge separately.
                if name == 'coverage_parts' and part_counts[feature['properties']['block_id']] > 1:
                    continue
                feature['geometry'], detail = simplify_display_geometry(display_con, feature['geometry'])
                if detail['retained_parts'] or detail['feature_fallback']:
                    fallbacks[f'{name}:{feature["id"]}'] = detail
    document['display_simplification'] = {
        'rules': DISPLAY_SIMPLIFICATION, 'engine': 'DuckDB ' + duckdb.__version__,
        'fallbacks': fallbacks,
        'coverage_parts_policy': 'retain detailed complementary pieces; simplify single-piece blocks',
        'retained_split_block_ids': retained_split_blocks,
    }
    # Prepared geometry remains authoritative: areas/classifications are copied
    # unchanged and are never measured again from simplified browser geometry.
    return {**document, 'title': 'Housing growth areas and mapped Tier 1B',
            'source_view': 'prepared housing growth blocks; selected FLU and Tier 1B stages per RPC',
            'source_urls': [row[0] for row in urls]}


EXPORTERS = {'interim-areas': export_interim, 'map': export_map, 'tier1b': export_tier1b,
             'housing-growth': export_housing_growth}


def export_all(db_path=DB_PATH, output=EXPORT_DIR, memberships_path=MEMBERSHIP_PATH):
    db_path, output = Path(db_path), Path(output)
    if not db_path.is_file():
        raise SystemExit(f'Database not found: {db_path}. Restore a saved snapshot with '
                         '`python transform.py --snapshot <directory>`.')
    with duckdb.connect(str(db_path), read_only=True) as con:
        con.execute('LOAD spatial')
        con.execute('BEGIN TRANSACTION')
        # Text avoids adding a timezone library merely to read DuckDB timestamps.
        run = con.execute('''SELECT run_id, CAST(completed_at AT TIME ZONE 'UTC' AS VARCHAR)
                             FROM latest_ingest_run''').fetchone()
        if not run:
            raise SystemExit('No successful capture in the database. Restore a snapshot or run make ingest.')
        common = {'schema_version': 1, 'snapshot_id': run[0],
                  'captured_at': run[1].replace(' ', 'T') + 'Z',
                  'exported_at': datetime.now(timezone.utc).isoformat()}
        memberships = load_prepared(con, memberships_path)
        datasets = {name: {**common, **(fn(con, memberships) if fn is export_map else fn(con))}
                    for name, fn in EXPORTERS.items()}
        con.execute('COMMIT')
    # Finish every query before publishing any new export.
    documents = {f'{name}.json': dataset for name, dataset in datasets.items()}
    documents['manifest.json'] = {
        **common, 'datasets': [{'id': name, 'file': f'{name}.json',
                              'schema_version': dataset['schema_version'],
                              'title': dataset['title'], 'source_view': dataset['source_view']}
                             for name, dataset in datasets.items()],
    }
    publish_json_directory(output, documents)
    for name, dataset in datasets.items():
        print(f'Exported {name}: {dataset.get("summary", {})} → {output / (name + ".json")}')


# Publish one complete export generation

def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n'


def publish_json_directory(output, documents):
    """Stage a full generation; restore the old directory if replacement fails.

    Local build commands should have one writer. Directory renames leave a short
    missing-path window, but never a directory containing mixed generations.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.exports-', dir=output.parent) as temp:
        stage = Path(temp) / 'new'
        backup = Path(temp) / 'previous'
        stage.mkdir()
        for name, value in documents.items():
            (stage / name).write_text(json_text(value), encoding='utf-8')
        if output.exists():
            output.rename(backup)
        try:
            stage.rename(output)
        except BaseException:
            if backup.exists():
                backup.rename(output)
            raise


# Static page assembly

def build(output=DASHBOARD_DIR):
    output = Path(output)
    dataset = json.loads((output / 'data' / 'interim-areas.json').read_text())
    map_dataset = json.loads((output / 'data' / 'map.json').read_text())
    tier_dataset = json.loads((output / 'data' / 'tier1b.json').read_text())
    housing_dataset = json.loads((output / 'data' / 'housing-growth.json').read_text())
    manifest = json.loads((output / 'data' / 'manifest.json').read_text())
    for key in ('snapshot_id', 'captured_at', 'exported_at'):
        if not manifest.get(key) or any(d.get(key) != manifest[key] for d in (dataset, map_dataset, tier_dataset, housing_dataset)):
            raise ValueError(f'Mismatched or missing export {key}; run make export.')
    if dataset['schema_version'] != 1:
        raise ValueError('Unsupported interim export schema')
    if map_dataset['schema_version'] != 2:
        raise ValueError('Unsupported map export schema')
    if tier_dataset['schema_version'] != 3:
        raise ValueError('Unsupported Tier 1B export schema')
    if housing_dataset['schema_version'] != 1:
        raise ValueError('Unsupported housing growth export schema')
    substitutions = {
        '{{LOGO}}': 'data:image/svg+xml;base64,' + base64.b64encode((ROOT / 'web' / 'assets' / 'lbh-logo.svg').read_bytes()).decode('ascii'),
        '{{STYLES}}': (ROOT / 'web' / 'dashboard.css').read_text(),
        '{{LEAFLET_CSS}}': (ROOT / 'web' / 'vendor' / 'leaflet.css').read_text(),
        '{{LEAFLET_JS}}': (ROOT / 'web' / 'vendor' / 'leaflet.js').read_text(),
        '{{SCRIPT}}': '\n'.join((ROOT / 'web' / name).read_text() for name in
                               ('story-animation.js', 'eligibility-display.js', 'stories.js',
                                'story-act181.js', 'story-overview.js', 'dashboard.js')),
    }
    html = (ROOT / 'web' / 'index.html').read_text()
    for marker, value in substitutions.items():
        if html.count(marker) != 1:
            raise ValueError(f'Expected exactly one template marker: {marker}')
        html = html.replace(marker, value)
    target = output / 'index.html'
    temp = target.with_suffix('.html.tmp')
    temp.write_text(html)
    temp.replace(target)
    print(f'Built {target} (data/ JSON required; embedded assets; online street basemap)')


# Saved capture status

def status(db_path=DB_PATH):
    if not Path(db_path).is_file():
        raise SystemExit('No ingest database yet. Restore a saved snapshot with make transform SNAPSHOT=…')
    with duckdb.connect(str(db_path), read_only=True) as con:
        run = con.execute('SELECT run_id, snapshot_path FROM latest_ingest_run').fetchone()
        if run is None:
            raise SystemExit('No successful ingest yet. Restore a completed snapshot.')
        print(f'Snapshot: {run[0]}\nFiles: {run[1]}\nDatabase: {db_path}\n')
        print(f'{"RPC":<6} {"Kind":<10} {"Stage":<18} {"Features":>8}  Layer')
        for rpc, kind, stage, count, path in con.execute('''
            SELECT coalesce(rpc, '-'), kind, stage, feature_count, path
            FROM current_layers ORDER BY kind, rpc, stage, layer_id''').fetchall():
            print(f'{rpc:<6} {kind:<10} {stage:<18} {count:>8}  {path}')
        print('\nInterim eligibility:')
        for row in con.execute('''SELECT category, count(*),
            count(*) FILTER (WHERE likely_eligible = true),
            count(*) FILTER (WHERE likely_eligible = false),
            count(*) FILTER (WHERE likely_eligible IS NULL)
            FROM interim_areas GROUP BY category ORDER BY category''').fetchall():
            print(f'  {row[0]}: {row[1]} total, {row[2]} likely eligible, '
                  f'{row[3]} likely not eligible, {row[4]} unknown')
        missing, invalid = con.execute('''SELECT count(*) FILTER (WHERE geom IS NULL),
            count(*) FILTER (WHERE geometry_valid = false) FROM current_features''').fetchone()
        unmapped = con.execute('SELECT count(*) FROM unmapped_features').fetchone()[0]
        print(f'\nRetained source records: {missing} missing geometry, {invalid} invalid geometry; '
              f'{unmapped} outside selected map filters.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--export', action='store_true', help='Export JSON only')
    mode.add_argument('--page', action='store_true', help='Build HTML from existing exports only')
    mode.add_argument('--status', action='store_true', help='Report saved capture coverage')
    parser.add_argument('--db', type=Path, default=DB_PATH)
    parser.add_argument('--output', type=Path, default=DASHBOARD_DIR)
    parser.add_argument('--memberships', type=Path, default=MEMBERSHIP_PATH)
    args = parser.parse_args()
    if args.status:
        status(args.db)
        return
    if not args.page:
        export_all(args.db, args.output / 'data', args.memberships)
    if not args.export:
        build(args.output)


if __name__ == '__main__':
    main()
