"""Report on prepared research data and build the standalone dashboard."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile

import duckdb
from config import ROOT, DB_PATH, DASHBOARD_DIR, EXPORT_DIR, MEMBERSHIP_PATH, MEMBERSHIP_VERSION
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
    if memberships is None:
        memberships = load_prepared(con)
    eligible_ids = {a['properties']['feature_id'] for a in areas
                    if a['properties']['likely_eligible'] is True}
    designated = {m['municipality_geoid'] for m in memberships}
    eligible = {m['municipality_geoid'] for m in memberships if m['feature_id'] in eligible_ids}
    for town in towns:
        props = town['properties']
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
EXPORTERS = {'interim-areas': export_interim, 'map': export_map}


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
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n'


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


# Standalone page assembly

def build(output=DASHBOARD_DIR):
    output = Path(output)
    dataset = json.loads((output / 'data' / 'interim-areas.json').read_text())
    map_dataset = json.loads((output / 'data' / 'map.json').read_text())
    manifest = json.loads((output / 'data' / 'manifest.json').read_text())
    for key in ('snapshot_id', 'captured_at', 'exported_at'):
        if not manifest.get(key) or any(d.get(key) != manifest[key] for d in (dataset, map_dataset)):
            raise ValueError(f'Mismatched or missing export {key}; run make export.')
    if dataset['schema_version'] != 1:
        raise ValueError('Unsupported interim export schema')
    if map_dataset['schema_version'] != 2:
        raise ValueError('Unsupported map export schema')
    # Embedded JSON lets the page work directly via file:// as well as a static
    # server. Escape HTML delimiters so source strings cannot close the script.
    payload = json.dumps(dataset, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    substitutions = {
        '{{LOGO}}': 'data:image/svg+xml;base64,' + base64.b64encode((ROOT / 'web' / 'assets' / 'lbh-logo.svg').read_bytes()).decode('ascii'),
        '{{STYLES}}': (ROOT / 'web' / 'dashboard.css').read_text(),
        '{{LEAFLET_CSS}}': (ROOT / 'web' / 'vendor' / 'leaflet.css').read_text(),
        '{{LEAFLET_JS}}': (ROOT / 'web' / 'vendor' / 'leaflet.js').read_text(),
        '{{SCRIPT}}': '\n'.join((ROOT / 'web' / name).read_text() for name in
                               ('story-animation.js', 'eligibility-display.js', 'dashboard.js')),
        '{{DATA}}': payload,
        '{{MAP_DATA}}': json.dumps(map_dataset, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e'),
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
    print(f'Built {target} (embedded data and assets; online street basemap)')


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
