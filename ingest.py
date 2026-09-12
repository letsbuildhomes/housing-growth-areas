"""Capture public Act 181 sources as dated GeoJSON snapshots and DuckDB layers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import duckdb
import config
from arcgis import download, fetch_json, object_id_field, query_ids
from ingest_sources import discover

SNAPSHOT_ROOT = config.IN_DIR / 'snapshots'
DB_PATH = config.DATA_DIR / 'act181_ingest.duckdb'


def write_json(path, value):
    path.write_text(json.dumps(value, separators=(',', ':'), ensure_ascii=False))


def sha256(path):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def capture(root=SNAPSHOT_ROOT, workers=4):
    started = datetime.now(timezone.utc)
    run_id = started.strftime('%Y%m%dT%H%M%S.%fZ')
    directory = root / run_id
    directory.mkdir(parents=True)
    documents, layers = discover()
    write_json(directory / 'map_documents.json', documents)
    sources = {layer['source_id']: layer['url'] for layer in layers}

    def capture_source(pair):
        sid, url = pair
        meta = fetch_json(url)
        if not meta.get('geometryType'):
            raise RuntimeError(f'Expected spatial layer: {url}')
        collection = download(url, meta)
        oid = object_id_field(meta)
        all_ids = {f['properties'][oid] for f in collection['features']}
        memberships = {}
        for layer in (l for l in layers if l['source_id'] == sid):
            ids = sorted(all_ids) if layer['where'] == '1=1' else query_ids(url, layer['where'])
            if not set(ids).issubset(all_ids):
                raise RuntimeError(f'Map membership changed during capture: {url}')
            memberships[layer['layer_id']] = ids
        if meta.get('editingInfo') != fetch_json(url).get('editingInfo'):
            raise RuntimeError(f'Source edited while capturing map membership: {url}')
        write_json(directory / (sid + '.geojson'), collection)
        write_json(directory / (sid + '_meta.json'), meta)
        print(f"  {meta['name']}: {len(all_ids)} features", flush=True)
        return dict(source_id=sid, url=url, count=len(all_ids), memberships=memberships)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        captured = list(pool.map(capture_source, sources.items()))
    manifest = dict(
        schema_version=1, run_id=run_id, started_at=started.isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(), crs='EPSG:4326',
        layers=layers, sources=captured,
        files={p.name: sha256(p) for p in directory.iterdir() if p.is_file()},
    )
    # No manifest means incomplete capture, never a reusable cache.
    write_json(directory / 'manifest.json', manifest)
    return directory


def pick(properties, *names):
    for name in names:
        value = properties.get(name)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            return value
    return None


def boolean(value):
    return {'Y': True, 'YES': True, 'N': False, 'NO': False}.get(str(value).strip().upper())


def decoded_properties(properties, meta):
    result = dict(properties)
    for field in meta['fields']:
        labels = {v['code']: v['name'] for v in (field.get('domain') or {}).get('codedValues', [])}
        value = properties.get(field['name'])
        if value in labels:
            result[field['name']] = labels[value]
    return result


def normalize(feature, meta, source, layers, run_id):
    props = feature['properties']
    sid = source['source_id']
    oid = props[object_id_field(meta)]
    contexts = [l for l in layers if l['source_id'] == sid]
    kinds = {l['kind'] for l in contexts}
    if len(kinds) != 1:
        raise RuntimeError(f'Conflicting source kinds: {source["url"]}')
    kind = next(iter(kinds))
    rpc = pick(props, 'RPC_CODE', 'RPC')
    rpc = config.RPC_NAME_TO_CODE.get(rpc, rpc)
    if rpc is None:
        hints = {l['rpc'] for l in contexts if l['rpc']}
        if len(hints) == 1:
            rpc = next(iter(hints))
    version = pick(props, 'TIER_VERS', 'VERS_RPC', 'VERSION')
    version = config.VERSION_NORMALIZE.get(version, version)
    flu_code = pick(props, 'FLU_AREA', 'FLU_Area')
    flu_code = config.FLU_NAME_TO_CODE.get(flu_code, flu_code)
    tier_code = pick(props, 'TIER_AREA')
    if tier_code is None and kind == 'tier' and all(l['path'][-1] == 'Tier 1B' for l in contexts):
        tier_code = '1B'
    category = contexts[0]['category']
    water_field = 'DW_Status' if category == 'village_center_buffer' else 'Water'
    sewer_field = 'WW_Status' if category == 'village_center_buffer' else 'Sewer'
    eligibility = pick(props, 'ExemptionApplied_Y_N_')
    eligible = boolean(eligibility)
    name = (pick(props, 'TOWNNAMEMC', 'TOWNNAME') if kind == 'municipality_boundary' else
            pick(props, 'LONGNAME', 'SHORTNAME', 'RPC') if kind == 'rpc_boundary' else
            pick(props, 'DIS_NAME', 'CommunityName', 'NAME', 'TOWNNAME', 'TOWN_NAME', 'MUNI'))
    municipality = (pick(props, 'TOWNNAMEMC', 'TOWNNAME') if kind == 'municipality_boundary'
                    else pick(props, 'TOWNNAME', 'TOWN_NAME', 'MUNI'))
    return dict(
        run_id=run_id, feature_id=f'{sid}:{oid}', source_id=sid, source_oid=str(oid),
        source_globalid=pick(props, 'GlobalID', 'GLOBALID'), kind=kind, category=category, rpc=rpc,
        name=name, municipality=municipality, geoid=pick(props, 'GEOID', 'TOWNGEOID'),
        flu_code=flu_code, tier_code=tier_code, submission_version=version,
        lurb_status=pick(props, 'LURBSTATUS'), date_lurb=pick(props, 'DATE_LURB'),
        exemption_type=pick(props, 'ExemptionArea'), exemption_description=pick(props, 'ExemptionAreaDescription'),
        eligibility_raw=eligibility, likely_eligible=eligible,
        eligibility_label=('Area likely Exemption Eligible' if eligible is True else
                           'Area likely NOT Exemption Eligible' if eligible is False else None),
        zoning_bylaws=boolean(props.get('ZoningAndSubdivisionBylaws')),
        drinking_water=boolean(props.get(water_field)), sewer_wastewater=boolean(props.get(sewer_field)),
        adequate_soils=boolean(props.get('AdequateSoils')),
        criteria_fields={key: field if field in props else None for key, field in {
            'zoning_bylaws': 'ZoningAndSubdivisionBylaws', 'drinking_water': water_field,
            'sewer_wastewater': sewer_field, 'adequate_soils': 'AdequateSoils',
        }.items()} if kind == 'interim' else {},
        raw_properties=props, decoded_properties=decoded_properties(props, meta),
        geometry_geojson=feature.get('geometry'),
    )


TEXT_COLUMNS = [
    'run_id', 'feature_id', 'source_id', 'source_oid', 'source_globalid', 'kind',
    'category', 'rpc', 'name', 'municipality', 'geoid', 'flu_code', 'tier_code',
    'submission_version', 'lurb_status', 'date_lurb', 'exemption_type',
    'exemption_description', 'eligibility_raw', 'eligibility_label',
]
BOOL_COLUMNS = ['likely_eligible', 'zoning_bylaws', 'drinking_water', 'sewer_wastewater', 'adequate_soils']
JSON_COLUMNS = ['criteria_fields', 'raw_properties', 'decoded_properties', 'geometry_geojson']
COLUMN_TYPES = {**{k: 'VARCHAR' for k in TEXT_COLUMNS},
                **{k: 'BOOLEAN' for k in BOOL_COLUMNS}, **{k: 'JSON' for k in JSON_COLUMNS}}


def initialize(con):
    con.execute('LOAD spatial')
    con.execute('''CREATE TABLE IF NOT EXISTS ingest_runs (
        run_id VARCHAR PRIMARY KEY, started_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
        snapshot_path VARCHAR, manifest JSON)''')
    con.execute('''CREATE TABLE IF NOT EXISTS ingest_sources (
        run_id VARCHAR, source_id VARCHAR, url VARCHAR, expected_count BIGINT,
        metadata JSON, PRIMARY KEY(run_id, source_id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS ingest_layers (
        run_id VARCHAR, layer_id VARCHAR, source_id VARCHAR, kind VARCHAR,
        category VARCHAR, stage VARCHAR, rpc VARCHAR, path JSON,
        definition_expression VARCHAR, definition JSON, feature_count BIGINT,
        PRIMARY KEY(run_id, layer_id))''')
    con.execute('''CREATE TABLE IF NOT EXISTS ingest_memberships (
        run_id VARCHAR, layer_id VARCHAR, feature_id VARCHAR,
        PRIMARY KEY(run_id, layer_id, feature_id))''')
    columns = ', '.join(f'{k} {v}' for k, v in COLUMN_TYPES.items())
    con.execute(f'''CREATE TABLE IF NOT EXISTS ingest_features (
        {columns}, geom GEOMETRY, geometry_valid BOOLEAN, PRIMARY KEY(run_id, feature_id))''')
    con.execute('''CREATE OR REPLACE VIEW latest_ingest_run AS
        SELECT * FROM ingest_runs ORDER BY started_at DESC LIMIT 1''')
    con.execute('''CREATE OR REPLACE VIEW current_features AS
        SELECT f.* FROM ingest_features f JOIN latest_ingest_run USING (run_id)''')
    con.execute('''CREATE OR REPLACE VIEW current_layers AS
        SELECT l.* FROM ingest_layers l JOIN latest_ingest_run USING (run_id)''')
    con.execute('''CREATE OR REPLACE VIEW unmapped_features AS
        SELECT f.* FROM current_features f WHERE NOT EXISTS (
            SELECT 1 FROM ingest_memberships m
            WHERE m.run_id = f.run_id AND m.feature_id = f.feature_id)''')
    con.execute('''CREATE OR REPLACE VIEW map_features AS
        SELECT f.*, l.layer_id, l.stage AS map_stage, l.rpc AS map_rpc, l.path AS map_path
        FROM current_features f JOIN ingest_memberships m USING (run_id, feature_id)
        JOIN current_layers l USING (run_id, layer_id)''')
    views = {
        'interim_areas': "kind = 'interim'",
        'interim_downtown_district': "category = 'downtown_district'",
        'interim_town_growth_development': "category = 'town_growth_development'",
        'interim_village_center_buffer': "category = 'village_center_buffer'",
        'tier1b_pre_application': "kind = 'tier' AND tier_code = '1B' AND map_stage = 'pre_application'",
        'tier1b_application': "kind = 'tier' AND tier_code = '1B' AND map_stage = 'application'",
        'tier_approved': "kind = 'tier' AND map_stage = 'approved'",
        'flu_pre_application': "kind = 'flu' AND map_stage = 'pre_application'",
        'flu_application': "kind = 'flu' AND map_stage = 'application'",
        'flu_approved': "kind = 'flu' AND map_stage = 'approved'",
        'hamlet_features': "kind = 'hamlet'",
        'municipal_boundaries': "kind = 'municipality_boundary'",
        'rpc_boundaries': "kind = 'rpc_boundary'",
    }
    for name, where in views.items():
        con.execute(f'CREATE OR REPLACE VIEW {name} AS SELECT * FROM map_features WHERE {where}')


def load_snapshot(directory, db_path=DB_PATH):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['schema_version'] != 1:
        raise RuntimeError('Unsupported snapshot schema')
    for name, expected in manifest['files'].items():
        if sha256(directory / name) != expected:
            raise RuntimeError(f'Snapshot checksum mismatch: {name}')
    run_id = manifest['run_id']
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        initialize(con)
        con.execute('BEGIN TRANSACTION')
        for table in ['ingest_memberships', 'ingest_features', 'ingest_layers', 'ingest_sources', 'ingest_runs']:
            con.execute(f'DELETE FROM {table} WHERE run_id = ?', [run_id])
        con.execute('INSERT INTO ingest_runs VALUES (?, ?, ?, ?, ?)', [
            run_id, manifest['started_at'], manifest['completed_at'], str(directory), json.dumps(manifest),
        ])
        layers = manifest['layers']
        for source in manifest['sources']:
            sid = source['source_id']
            meta = json.loads((directory / (sid + '_meta.json')).read_text())
            features = json.loads((directory / (sid + '.geojson')).read_text())['features']
            if len(features) != source['count']:
                raise RuntimeError(f'Snapshot count mismatch: {sid}')
            con.execute('INSERT INTO ingest_sources VALUES (?, ?, ?, ?, ?)',
                        [run_id, sid, source['url'], source['count'], json.dumps(meta)])
            # Explicit types preserve all-null fields, GEOIDs and source dates.
            row_path = directory / (sid + '_normalized.ndjson')
            try:
                with row_path.open('w') as stream:
                    for feature in features:
                        stream.write(json.dumps(normalize(feature, meta, source, layers, run_id)) + '\n')
                if features:
                    columns = ', '.join(COLUMN_TYPES)
                    types_sql = '{' + ','.join(f"'{k}':'{v}'" for k, v in COLUMN_TYPES.items()) + '}'
                    con.execute(f'''INSERT INTO ingest_features
                        SELECT {columns}, ST_GeomFromGeoJSON(geometry_geojson),
                            ST_IsValid(ST_GeomFromGeoJSON(geometry_geojson))
                        FROM read_json(?, format='newline_delimited', columns={types_sql},
                                       maximum_object_size=100000000)''', [str(row_path)])
            finally:
                row_path.unlink(missing_ok=True)
            for layer in (l for l in layers if l['source_id'] == sid):
                ids = source['memberships'][layer['layer_id']]
                con.execute('INSERT INTO ingest_layers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [
                    run_id, layer['layer_id'], sid, layer['kind'], layer['category'], layer['stage'],
                    layer['rpc'], json.dumps(layer['path']), layer['where'],
                    json.dumps(layer['map_definition']), len(ids),
                ])
                if ids:
                    con.execute('''INSERT INTO ingest_memberships
                        SELECT ?, ?, ? || ':' || CAST(oid AS VARCHAR) FROM unnest(?) AS t(oid)''',
                        [run_id, layer['layer_id'], sid, ids])
        missing = con.execute('''SELECT count(*) FROM ingest_memberships m
            LEFT JOIN ingest_features f USING (run_id, feature_id)
            WHERE m.run_id = ? AND f.feature_id IS NULL''', [run_id]).fetchone()[0]
        if missing:
            raise RuntimeError(f'{missing} memberships refer to missing features')
        expected = sum(s['count'] for s in manifest['sources'])
        actual = con.execute('SELECT count(*) FROM ingest_features WHERE run_id = ?', [run_id]).fetchone()[0]
        if actual != expected:
            raise RuntimeError(f'Database count mismatch: {actual} != {expected}')
        con.execute('COMMIT')
        print(f'Loaded {actual} source features from {len(manifest["sources"])} services into {db_path}')
        for row in con.execute('''SELECT kind, map_stage, count(*) FROM map_features
                                  GROUP BY ALL ORDER BY 1,2''').fetchall():
            print(' ', *row)
        issues = con.execute('''SELECT count(*) FILTER (WHERE geom IS NULL),
            count(*) FILTER (WHERE geometry_valid = false) FROM current_features''').fetchone()
        print(f'Geometry: {issues[0]} missing, {issues[1]} invalid (retained without alteration)')
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, help='Load a completed snapshot without network access')
    parser.add_argument('--db', type=Path, default=DB_PATH)
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 9))
    args = parser.parse_args()
    directory = args.snapshot or capture(workers=args.workers)
    load_snapshot(directory, args.db)
    print(f'Snapshot: {directory}')


if __name__ == '__main__':
    main()
