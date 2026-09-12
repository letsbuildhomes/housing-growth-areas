"""Export compact, versioned website datasets from the existing database only."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'data' / 'act181_ingest.duckdb'
OUTPUT = ROOT / 'out' / 'dashboard' / 'data'
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


def export_map(con):
    """Export only the geometries and attributes needed by the offline map."""
    area_fields = ['feature_id', 'name', 'municipality', 'category', 'likely_eligible']
    area_rows = con.execute('''SELECT feature_id, name, municipality, category,
                                      likely_eligible, ST_AsGeoJSON(geom)
                               FROM interim_areas
                               ORDER BY feature_id''').fetchall()
    town_fields = ['feature_id', 'name', 'municipality', 'geoid', 'has_designated_area', 'has_likely_eligible']
    town_rows = con.execute('''SELECT t.feature_id, t.name, t.municipality, t.geoid,
                                     EXISTS (
                                       SELECT 1 FROM interim_areas a
                                       WHERE a.geom IS NOT NULL AND t.geom IS NOT NULL
                                         AND ST_Intersects(t.geom, a.geom)
                                     ) AS has_designated_area,
                                     EXISTS (
                                       SELECT 1 FROM interim_areas a
                                       WHERE a.likely_eligible IS TRUE
                                         AND a.geom IS NOT NULL AND t.geom IS NOT NULL
                                         AND ST_Intersects(t.geom, a.geom)
                                     ) AS has_likely_eligible,
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
    rpcs = [geojson_feature(row, rpc_fields) for row in rpc_rows]
    return {
        'title': 'Interim areas and Vermont boundary reference layers',
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


def write_json(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n')
    temp.replace(path)


def export_all(db_path=DB_PATH, output=OUTPUT):
    db_path, output = Path(db_path), Path(output)
    if not db_path.is_file():
        raise SystemExit(f'Database not found: {db_path}. Restore a saved snapshot with '
                         '`python extract.py --snapshot <directory>`, or explicitly run `make ingest`.')
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
        datasets = {name: {**common, **fn(con)} for name, fn in EXPORTERS.items()}
        con.execute('COMMIT')
    # Finish every query before publishing any new export.
    output.mkdir(parents=True, exist_ok=True)
    for name, dataset in datasets.items():
        write_json(output / f'{name}.json', dataset)
    write_json(output / 'manifest.json', {
        **common, 'datasets': [{'id': name, 'file': f'{name}.json',
                              'title': dataset['title'], 'source_view': dataset['source_view']}
                             for name, dataset in datasets.items()],
    })
    for name, dataset in datasets.items():
        print(f'Exported {name}: {dataset.get("summary", {})} → {output / (name + ".json")}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DB_PATH)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    export_all(args.db, args.output)
