"""Load saved snapshots and prepare municipality relationships without downloads."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

import duckdb
import config
from arcgis import object_id_field
from config import DB_PATH, MEMBERSHIP_PATH, MEMBERSHIP_VERSION, ALIASES, RUTLAND_FEATURES


# File validation and publication

def sha256(path):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n'


def write_json(path, value):
    path = Path(path)
    content = json_text(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(content)
            stream.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


# Snapshot normalization and database loading

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
    create_tier1b_working_view(con)


def create_tier1b_working_view(con):
    """Select the furthest populated map stage per source RPC, retaining raw rows."""
    con.execute('''CREATE OR REPLACE VIEW tier1b_working AS
        SELECT * FROM map_features
        WHERE kind = 'tier' AND tier_code = '1B'
          AND map_stage IN ('pre_application', 'application', 'approved')
        QUALIFY dense_rank() OVER (PARTITION BY rpc ORDER BY
            CASE map_stage WHEN 'approved' THEN 3 WHEN 'application' THEN 2 ELSE 1 END
            DESC) = 1''')


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
            scratch = tempfile.TemporaryDirectory(prefix='act181-normalized-')
            row_path = Path(scratch.name) / 'normalized.ndjson'
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
                scratch.cleanup()
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


# Municipality relationships

def normalize_label(value):
    return ' '.join((value or '').split()).casefold()


def derive_memberships(areas, towns):
    """Return one relationship per source area and official municipality GEOID.

    Missing labels, targets, ambiguous boundaries, or unreviewed Rutland records
    fail explicitly. Geometry is not consulted, even when it is missing.
    """
    by_name, geoids = {}, set()
    for town in towns:
        key, geoid = normalize_label(town['municipality']), town['geoid']
        if not key or not geoid or key in by_name or geoid in geoids:
            raise ValueError(f'Ambiguous/missing municipality name or GEOID: {town}')
        by_name[key] = town
        geoids.add(geoid)
    result, seen = [], set()
    for area in areas:
        fid, key = area['feature_id'], normalize_label(area['municipality'])
        if fid in seen:
            raise ValueError(f'Duplicate source area: {fid}')
        seen.add(fid)
        if key == 'rutland':
            if fid not in RUTLAND_FEATURES or area['category'] != 'town_growth_development':
                raise ValueError(f'Review municipality membership for {fid}: Rutland')
            targets, method = ('Rutland City',), 'approved_feature_override'
        elif key in ALIASES:
            targets, method = ALIASES[key], 'approved_alias'
        elif key in by_name:
            targets, method = (by_name[key]['municipality'],), 'normalized_exact'
        else:
            raise ValueError(f'Review municipality membership for {fid}: {area["municipality"]!r}')
        for target in targets:
            town = by_name.get(normalize_label(target))
            if town is None:
                raise ValueError(f'Missing approved municipality target {target} for {fid}')
            result.append({'feature_id': fid, 'source_municipality': area['municipality'],
                           'municipality': town['municipality'], 'municipality_geoid': town['geoid'],
                           'method': method})
    return result


MEMBERSHIP_BASIS = 'recorded municipality with approved crosswalk; no spatial fallback'


def inputs(con):
    def records(query, fields):
        return [dict(zip(fields, row)) for row in con.execute(query).fetchall()]
    areas = records('SELECT feature_id, municipality, category FROM interim_areas ORDER BY feature_id',
                    ['feature_id', 'municipality', 'category'])
    towns = records("SELECT municipality, geoid FROM current_features WHERE kind = 'municipality_boundary' ORDER BY feature_id",
                    ['municipality', 'geoid'])
    return areas, towns


def provenance(con):
    run = con.execute('SELECT run_id FROM latest_ingest_run').fetchone()
    if not run:
        raise ValueError('No successful capture. Restore a completed snapshot.')
    areas, towns = inputs(con)
    metadata = {
        'schema_version': 1, 'snapshot_id': run[0],
        'membership_version': MEMBERSHIP_VERSION, 'membership_basis': MEMBERSHIP_BASIS,
        'rules_sha256': hashlib.sha256(json.dumps({
            'version': MEMBERSHIP_VERSION, 'aliases': ALIASES,
            'rutland_features': sorted(RUTLAND_FEATURES),
        }, sort_keys=True).encode()).hexdigest(),
        'inputs_sha256': hashlib.sha256(json.dumps([areas, towns], sort_keys=True).encode()).hexdigest(),
    }
    return metadata, areas, towns


def prepare(db_path=DB_PATH, output=MEMBERSHIP_PATH):
    if not Path(db_path).is_file():
        raise SystemExit(f'Database not found: {db_path}. Restore a saved snapshot with make transform SNAPSHOT=…')
    with duckdb.connect(str(db_path), read_only=True) as con:
        con.execute('BEGIN TRANSACTION')
        metadata, areas, towns = provenance(con)
        document = {**metadata, 'memberships': derive_memberships(areas, towns)}
        con.execute('COMMIT')
    # Avoid invalidating downstream timestamps when the prepared data is unchanged.
    output = Path(output)
    if not output.exists() or json.loads(output.read_text()) != document:
        write_json(output, document)
    print(f'Prepared {len(document["memberships"])} municipality relationships → {output}')
    return document


def load_prepared(con, path=MEMBERSHIP_PATH):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Missing municipality relationships; run make prepare.')
    document = json.loads(path.read_text())
    expected, _, _ = provenance(con)
    if any(document.get(key) != value for key, value in expected.items()):
        raise ValueError('Stale municipality relationships; run make prepare.')
    return document['memberships']


def tier_inputs(con):
    rows = con.execute('''SELECT run_id, feature_id, layer_id, source_id, source_oid,
        rpc, map_stage, submission_version, lurb_status, ST_AsGeoJSON(geom)
        FROM map_features WHERE kind='tier' AND tier_code='1B'
        AND map_stage IN ('pre_application','application','approved')
        ORDER BY rpc,map_stage,layer_id,feature_id''').fetchall()
    towns = con.execute('''SELECT geoid,municipality,ST_AsGeoJSON(geom)
        FROM current_features WHERE kind='municipality_boundary' ORDER BY geoid''').fetchall()
    stamp = {'schema_version': 1, 'snapshot_id': con.execute(
        'SELECT run_id FROM latest_ingest_run').fetchone()[0], 'rules': config.TIER_RULES,
        'inputs_sha256': hashlib.sha256(json.dumps([rows,towns]).encode()).hexdigest()}
    return stamp, rows, towns


def derive_tier_municipal(con):
    """Spatial assignment in meters. Temporary tables never modify ingest data."""
    stamp, rows, towns = tier_inputs(con)
    band = config.TIER_RULES['boundary_band_m']
    radius = config.TIER_RULES['closing_radius_m']
    minimum = config.TIER_RULES['minimum_part_m2']
    crs = config.TIER_RULES['crs']
    con.execute('CREATE OR REPLACE TEMP TABLE tier_towns (geoid VARCHAR, name VARCHAR, g GEOMETRY, core GEOMETRY)')
    for geoid,name,geo in towns:
        con.execute('''INSERT INTO tier_towns SELECT ?,?,g,ST_Buffer(g,?) FROM
            (SELECT ST_MakeValid(ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true)) g)''',
            [geoid,name,-band,geo,crs])
    con.execute('CREATE OR REPLACE TEMP TABLE assigned (geoid VARCHAR,rpc VARCHAR,stage VARCHAR,source_index INTEGER,g GEOMETRY)')
    audit = {'removed_parts': [], 'unassigned_parts': [], 'repairs': [], 'sources': []}
    for index,row in enumerate(rows):
        run,fid,lid,sid,oid,rpc,stage,version,status,geo = row
        audit['sources'].append(dict(feature_id=fid,layer_id=lid,source_id=sid,source_oid=oid,
                                     rpc=rpc,map_stage=stage,submission_version=version,lurb_status=status))
        if geo is None:
            audit['unassigned_parts'].append({'source_index':index,'reason':'missing geometry'})
            continue
        con.execute('''CREATE OR REPLACE TEMP TABLE source_geom AS SELECT
            ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true) g''',[geo,crs])
        if not con.execute('SELECT ST_IsValid(g) FROM source_geom').fetchone()[0]:
            audit['repairs'].append({'source_index':index,'operation':'source validity repair'})
        parts = con.execute('''SELECT ST_AsWKB(part.geom) FROM source_geom,
            unnest(ST_Dump(ST_CollectionExtract(ST_MakeValid(g),3))) parts(part)''').fetchall()
        for part_index,(wkb,) in enumerate(parts):
            con.execute('CREATE OR REPLACE TEMP TABLE part AS SELECT ST_GeomFromWKB(?) g',[wkb])
            area = con.execute('SELECT ST_Area(g) FROM part').fetchone()[0]
            if area < minimum:
                audit['removed_parts'].append(dict(source_index=index,part=part_index,area_m2=area,operation='input'))
                continue
            # Qualification is per intersected connected component, not touching bounds.
            con.execute('''CREATE OR REPLACE TEMP TABLE qualified AS SELECT DISTINCT t.geoid FROM
                tier_towns t,part p,unnest(ST_Dump(ST_CollectionExtract(ST_Intersection(t.g,p.g),3))) pieces(piece)
                WHERE ST_Intersects(t.g,p.g) AND ST_Area(piece.geom)>0 AND ST_Intersects(piece.geom,t.core)''')
            ids = con.execute('SELECT geoid FROM qualified ORDER BY geoid').fetchall()
            if not ids:
                audit['unassigned_parts'].append(dict(source_index=index,part=part_index,area_m2=area,
                    geometry_wkb_hex=bytes(wkb).hex(),reason='no qualifying municipality'))
                continue
            if len(ids)==1:
                con.execute('INSERT INTO assigned SELECT ?,?,?,?,g FROM part',[ids[0][0],rpc,stage,index])
            else:
                con.execute('''CREATE OR REPLACE TEMP TABLE splits AS SELECT t.geoid,
                    ST_CollectionExtract(ST_Intersection(t.g,p.g),3) g
                    FROM tier_towns t JOIN qualified q USING(geoid),part p''')
                con.execute('INSERT INTO assigned SELECT geoid,?,?,?,g FROM splits',[rpc,stage,index])
                # Preserve minor external protrusions: attach each to nearest qualifying split.
                residuals = con.execute('''SELECT ST_AsWKB(piece.geom) FROM part,
                    (SELECT ST_Union_Agg(g) covered FROM splits),
                    unnest(ST_Dump(ST_CollectionExtract(ST_Difference(g,covered),3))) pieces(piece)
                    WHERE ST_Area(piece.geom)>0''').fetchall()
                for (residual,) in residuals:
                    owner = con.execute('''SELECT geoid FROM splits ORDER BY
                        ST_Distance(g,ST_Centroid(ST_GeomFromWKB(?))),geoid LIMIT 1''',[residual]).fetchone()[0]
                    con.execute('INSERT INTO assigned VALUES (?,?,?,?,ST_GeomFromWKB(?))',[owner,rpc,stage,index,residual])
    features=[]
    groups=con.execute('''SELECT a.geoid,t.name,a.rpc,a.stage,list(DISTINCT source_index ORDER BY source_index),
        ST_AsWKB(ST_Union_Agg(a.g)) FROM assigned a JOIN tier_towns t USING(geoid)
        GROUP BY a.geoid,t.name,a.rpc,a.stage ORDER BY a.rpc,t.name,a.stage''').fetchall()
    for geoid,name,rpc,stage,sources,wkb in groups:
        con.execute('''CREATE OR REPLACE TEMP TABLE merged AS SELECT ST_MakeValid(ST_GeomFromWKB(?)) g''',[wkb])
        # Closing is not clipped to municipal boundaries: whole-part assignments retain protrusions.
        con.execute('''CREATE OR REPLACE TEMP TABLE closed AS SELECT
            ST_CollectionExtract(ST_MakeValid(ST_Buffer(ST_Buffer(g,?),-?)),3) g FROM merged''',[radius,radius])
        removed=con.execute('''SELECT ST_Area(piece.geom) FROM closed,unnest(ST_Dump(g)) pieces(piece)
            WHERE ST_Area(piece.geom)<?''',[minimum]).fetchall()
        audit['removed_parts'].extend(dict(geoid=geoid,stage=stage,area_m2=a,operation='output') for (a,) in removed)
        con.execute('''CREATE OR REPLACE TEMP TABLE final_tier AS SELECT ST_Union_Agg(piece.geom) g
            FROM closed,unnest(ST_Dump(g)) pieces(piece) WHERE ST_Area(piece.geom)>=?''',[minimum])
        result=con.execute('''SELECT ST_IsValid(g),ST_Area(g),ST_AsGeoJSON(
            ST_Transform(g,?,'EPSG:4326',always_xy:=true)) FROM final_tier''',[crs]).fetchone()
        if result[2] is None:
            continue
        if not result[0]:
            raise ValueError(f'Invalid derived Tier 1B geometry: {name} {stage}')
        before=con.execute('SELECT ST_Area(g) FROM merged').fetchone()[0]
        features.append({'type':'Feature','id':f'{rpc}:{geoid}:{stage}',
            'properties':dict(feature_id=f'{rpc}:{geoid}:{stage}',municipality=name,geoid=geoid,
                rpc=rpc,map_stage=stage,source_indices=sources,area_m2=result[1],
                area_before_closing_m2=before), 'geometry':json.loads(result[2])})
    rank={'pre_application':1,'application':2,'approved':3}
    selected={}
    for row in rows:
        rpc,stage=row[5:7]
        if rank[stage]>rank.get(selected.get(rpc),0): selected[rpc]=stage
    return {**stamp,'selected_stages':selected,'areas':{'type':'FeatureCollection','features':features},'audit':audit}


def prepare_tier(db_path=DB_PATH, output=None):
    output=Path(output) if output else Path(db_path).parent/'tier1b-municipal.json'
    if not Path(db_path).is_file(): raise ValueError('Restore the saved database first')
    with duckdb.connect(str(db_path),read_only=True) as con:
        con.execute('LOAD spatial')
        con.execute('BEGIN TRANSACTION')
        stamp,_,_=tier_inputs(con)
        if output.is_file():
            saved=json.loads(output.read_text())
            if all(saved.get(k)==v for k,v in stamp.items()):
                return
        document=derive_tier_municipal(con)
        con.execute('COMMIT')
    write_json(output,document)
    print(f'Prepared {len(document["areas"]["features"])} municipal Tier 1B stage records → {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot', type=Path, help='Load this completed raw snapshot')
    source.add_argument('--prepare', action='store_true', help='Prepare relationships from the existing read-only database')
    parser.add_argument('--db', type=Path, default=DB_PATH)
    parser.add_argument('--memberships', type=Path, default=MEMBERSHIP_PATH)
    args = parser.parse_args()
    if args.snapshot:
        load_snapshot(args.snapshot, args.db)
    prepare(args.db, args.memberships)
    prepare_tier(args.db)


if __name__ == '__main__':
    main()
