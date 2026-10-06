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


def derive_tier_municipal(con, input_data=None):
    """Spatial assignment in meters. Temporary tables never modify ingest data."""
    stamp, rows, towns = input_data if input_data is not None else tier_inputs(con)
    rules = stamp['rules']
    band = rules['boundary_band_m']
    radius = rules['closing_radius_m']
    minimum = rules['minimum_part_m2']
    # A part that vanishes under this inward buffer is narrower than minimum_width_m everywhere.
    inset = rules['minimum_width_m']/2
    crs = rules['crs']
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
            unnest(ST_Dump(ST_CollectionExtract(ST_MakeValid(g),3))) parts(part)
            WHERE ST_Area(part.geom)>0''').fetchall()
        if not parts:
            audit['unassigned_parts'].append({'source_index':index,'reason':'no polygon geometry after repair'})
        for part_index,(wkb,) in enumerate(parts):
            con.execute('CREATE OR REPLACE TEMP TABLE part AS SELECT ST_GeomFromWKB(?) g',[wkb])
            area,thin = con.execute('SELECT ST_Area(g),ST_IsEmpty(ST_Buffer(g,-?)) FROM part',[inset]).fetchone()
            if area < minimum or thin:
                audit['removed_parts'].append(dict(source_index=index,part=part_index,area_m2=area,operation='input',
                                                   reason='area' if area < minimum else 'width'))
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
        con.execute('''CREATE OR REPLACE TEMP TABLE closed_parts AS SELECT piece.geom g,ST_Area(piece.geom) area,
            ST_Area(piece.geom)<? OR ST_IsEmpty(ST_Buffer(piece.geom,-?)) removed
            FROM closed,unnest(ST_Dump(g)) pieces(piece)''',[minimum,inset])
        removed=con.execute('SELECT area FROM closed_parts WHERE removed ORDER BY area').fetchall()
        audit['removed_parts'].extend(dict(geoid=geoid,stage=stage,area_m2=a,operation='output',
                                           reason='area' if a < minimum else 'width') for (a,) in removed)
        con.execute('''CREATE OR REPLACE TEMP TABLE final_tier AS SELECT ST_Union_Agg(g) g
            FROM closed_parts WHERE NOT removed''')
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


def prepare_tier(db_path=DB_PATH, output=None, force=False):
    output=Path(output) if output else Path(db_path).parent/'tier1b-municipal.json'
    if not Path(db_path).is_file(): raise ValueError('Restore the saved database first')
    with duckdb.connect(str(db_path),read_only=True) as con:
        con.execute('LOAD spatial')
        con.execute('BEGIN TRANSACTION')
        stamp,_,_=tier_inputs(con)
        if output.is_file() and not force:
            saved=json.loads(output.read_text())
            if all(saved.get(k)==v for k,v in stamp.items()):
                return
        document=derive_tier_municipal(con)
        con.execute('COMMIT')
    write_json(output,document)
    print(f'Prepared {len(document["areas"]["features"])} municipal Tier 1B stage records → {output}')


def housing_inputs(con):
    """Fingerprint every stage, including non-housing FLU and absent geometry."""
    rows = con.execute('''SELECT run_id,feature_id,layer_id,source_id,source_oid,rpc,
        map_stage,submission_version,lurb_status,ST_AsGeoJSON(geom),flu_code,date_lurb
        FROM map_features WHERE kind='flu'
        AND map_stage IN ('pre_application','application','approved')
        ORDER BY rpc,map_stage,layer_id,feature_id''').fetchall()
    tier_stamp, tier_rows, towns = tier_inputs(con)
    rpc_rows = con.execute('''SELECT rpc,ST_AsGeoJSON(geom) FROM rpc_boundaries
        ORDER BY rpc,feature_id''').fetchall()
    dates = con.execute("SELECT feature_id,date_lurb FROM map_features WHERE kind='tier' ORDER BY feature_id,date_lurb").fetchall()
    stamp = {'schema_version': 1, 'snapshot_id': tier_stamp['snapshot_id'],
             'lineage_version': 1,
             'rules': config.HOUSING_RULES, 'tier_processing_rules': config.TIER_RULES,
             'inputs_sha256': hashlib.sha256(json.dumps([rows,tier_rows,towns,rpc_rows,dates]).encode()).hexdigest()}
    return stamp, rows, towns


def selected_map_stages(rows):
    rank = {'pre_application': 1, 'application': 2, 'approved': 3}
    selected = {}
    for row in rows:
        rpc, stage = row[5:7]
        if rank[stage] > rank.get(selected.get(rpc), 0):
            selected[rpc] = stage
    return selected


def housing_coverage(area, covered, rules=None):
    """Allow 1% discrepancy, or up to 5% when also below the acreage limit."""
    rules = rules or config.HOUSING_RULES
    tolerance = max(area * rules.get('coverage_near_complete_fraction',0),
                    min(area * rules['coverage_tolerance_fraction'], rules['coverage_tolerance_m2']))
    if area <= 0:
        return 'unknown'
    if area - covered <= tolerance:
        return 'substantial'
    if covered <= tolerance:
        return 'none'
    return 'partial'


def housing_boundary_context(con, audit):
    """Retain polygons excluded by the existing assignment rule as visual context.

    Failing municipality interior qualification excludes a valid component from
    analysis; it is not a data failure or a claim about its intended ownership.
    Missing/nonpolygon geometry remains a preparation failure.
    """
    excluded, features = set(), []
    for item in audit['unassigned_parts']:
        if item.get('reason') != 'no qualifying municipality' or 'geometry_wkb_hex' not in item:
            continue
        wkb = bytes.fromhex(item['geometry_wkb_hex'])
        valid,area,geometry = con.execute("""SELECT ST_IsValid(g),ST_Area(g),ST_AsGeoJSON(
            ST_Transform(g,?,'EPSG:4326',always_xy:=true)) FROM
            (SELECT ST_GeomFromWKB(?) g)""",[config.HOUSING_RULES['crs'],wkb]).fetchone()
        if not valid or area <= 0:
            continue
        source = audit['sources'][item['source_index']]
        digest = hashlib.sha256(wkb).hexdigest()
        fid = f'{source["feature_id"]}:context:{digest[:16]}'
        features.append({'type':'Feature','id':fid,'geometry':json.loads(geometry),
            'properties':dict(feature_id=fid,rpc=source['rpc'],map_stage=source['map_stage'],
                flu_code=source['flu_code'],source_indices=[item['source_index']],
                source_part=item['part'],geometry_sha256=digest,area_m2=area,
                context_reason='outside_municipality_assignment',analytical_included=False)})
        item['analytical_exclusion'] = 'outside_municipality_assignment'
        item['geometry_sha256'] = digest
        excluded.add((item['source_index'],item['part']))
    return features, excluded


def split_housing_block(con, wkb, tier_geo, crs):
    """Partition one block in meters, absorbing hairline boundary slivers.

    Growth and Tier maps trace nearly identical edges, so an exact overlay
    leaves thousands of hairline pieces. Each piece narrower than twice
    `coverage_sliver_m` joins the kind of its nearest wider piece in the block,
    the largest one when several touch (or keeps its own kind without one).
    Intersection and difference are separate overlays, so a sliver can miss its
    neighbor by float noise, and runs of slivers may touch only each other.
    Reassigning kinds never moves geometry, so the kinds still tile the block.
    Returns the exact covered area and (kind, area_m2, WGS84 GeoJSON) portions.
    """
    radius = config.HOUSING_RULES['coverage_sliver_m']
    con.execute('''CREATE OR REPLACE TEMP TABLE block_coverage AS
        WITH input AS (SELECT ST_GeomFromWKB(?) g,COALESCE(
                ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true),
                ST_GeomFromText('POLYGON EMPTY')) t),
            overlay AS (SELECT ST_CollectionExtract(ST_Intersection(g,t),3) covered,
                ST_CollectionExtract(ST_Difference(g,t),3) uncovered FROM input),
            pieces AS (SELECT row_number() OVER () id,exact_kind,piece.geom g,ST_Area(piece.geom) area,
                ST_IsEmpty(ST_Buffer(piece.geom,-?)) thin FROM
                (SELECT 'covered' exact_kind,covered shape FROM overlay
                 UNION ALL SELECT 'uncovered',uncovered FROM overlay),unnest(ST_Dump(shape)) parts(piece)
                WHERE ST_Area(piece.geom)>0),
            absorbed AS (SELECT p.id,q.exact_kind kind FROM pieces p JOIN pieces q
                ON p.thin AND NOT q.thin
                QUALIFY row_number() OVER (PARTITION BY p.id ORDER BY ST_Distance(p.g,q.g),q.area DESC)=1)
        SELECT exact_kind,COALESCE(a.kind,exact_kind) kind,g FROM pieces LEFT JOIN absorbed a USING(id)''',
        [wkb,tier_geo,crs,radius])
    exact_m2 = con.execute('''SELECT COALESCE(sum(ST_Area(g)),0) FROM block_coverage
        WHERE exact_kind='covered' ''').fetchone()[0]
    portions = []
    # Transformed rings can touch themselves at float precision; repair is display-only.
    rows = con.execute('''SELECT kind,ST_Area(g),ST_IsValid(g),ST_IsValid(w),ST_AsGeoJSON(w) FROM
        (SELECT kind,g,ST_CollectionExtract(ST_MakeValid(ST_Transform(g,?,'EPSG:4326',always_xy:=true)),3) w FROM
            (SELECT kind,ST_CollectionExtract(ST_Union_Agg(g),3) g FROM block_coverage GROUP BY kind))
        ORDER BY kind''',[crs]).fetchall()
    for kind,area,valid,display_valid,geo in rows:
        if not valid or not display_valid:
            raise ValueError(f'Invalid derived housing coverage portion: {kind}')
        portions.append((kind,area,json.loads(geo)))
    return exact_m2,portions


def derive_housing_growth(con):
    stamp, all_rows, towns = housing_inputs(con)
    selected = selected_map_stages(all_rows)
    rows = [row for row in all_rows if row[6] == selected[row[5]]
            and row[10] in config.HOUSING_RULES['categories']]
    # Reuse precisely the municipal Tier assignment, without changing interim memberships.
    municipal = derive_tier_municipal(con, (stamp, [row[:10] for row in rows], towns))
    con.execute('CREATE OR REPLACE TEMP TABLE housing_assigned AS SELECT * FROM assigned')
    sources = municipal['audit']['sources']
    for source, row in zip(sources, rows):
        source.update(flu_code=row[10], date_lurb=row[11])
    con.execute('CREATE OR REPLACE TEMP TABLE housing_source (source_index INTEGER,flu_code VARCHAR)')
    for i, row in enumerate(rows):
        con.execute('INSERT INTO housing_source VALUES (?,?)', [i,row[10]])
    context_features,context_excluded = housing_boundary_context(con,municipal['audit'])
    crs = config.HOUSING_RULES['crs']
    categories = []
    category_rows = con.execute('''SELECT a.geoid,t.name,a.rpc,a.stage,s.flu_code,
        list(DISTINCT a.source_index ORDER BY a.source_index),ST_AsGeoJSON(
        ST_Transform(ST_Union_Agg(a.g),?,'EPSG:4326',always_xy:=true))
        FROM housing_assigned a JOIN tier_towns t USING(geoid)
        JOIN housing_source s USING(source_index)
        GROUP BY a.geoid,t.name,a.rpc,a.stage,s.flu_code
        ORDER BY a.rpc,t.name,s.flu_code''',[crs]).fetchall()
    for geoid,name,rpc,stage,code,indices,geo in category_rows:
        categories.append({'type':'Feature','id':f'{rpc}:{geoid}:{stage}:{code}',
            'properties':dict(geoid=geoid,municipality=name,rpc=rpc,map_stage=stage,
                flu_code=code,source_indices=indices), 'geometry':json.loads(geo)})
    tier = derive_tier_municipal(con)
    tier_selected = tier['selected_stages']
    tier_lookup = {(f['properties']['rpc'],f['properties']['geoid']): f for f in tier['areas']['features']
                   if f['properties']['map_stage'] == tier_selected[f['properties']['rpc']]}
    def regional_unions(features):
        con.execute('CREATE OR REPLACE TEMP TABLE regional_shapes (rpc VARCHAR,g GEOMETRY)')
        for feature in features:
            con.execute('INSERT INTO regional_shapes SELECT ?,ST_GeomFromGeoJSON(?)',
                        [feature['properties']['rpc'],json.dumps(feature['geometry'])])
        return dict(con.execute('SELECT rpc,ST_AsGeoJSON(ST_Union_Agg(g)) FROM regional_shapes GROUP BY rpc').fetchall())
    housing_regions = regional_unions(municipal['areas']['features'])
    context_regions = regional_unions(context_features)
    context_masks = {}
    for rpc,geo in context_regions.items():
        # An excluded source component must never erase accepted housing acreage.
        mask = con.execute('''SELECT ST_AsWKB(ST_CollectionExtract(ST_Difference(
            ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true),
            COALESCE(ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true),
            ST_GeomFromText('POLYGON EMPTY'))),3))''',
            [geo,crs,housing_regions.get(rpc),crs]).fetchone()[0]
        context_masks[rpc] = mask
    def clip_tier_geometry(geo,rpc):
        result = con.execute('''SELECT ST_Area(g),ST_AsGeoJSON(ST_Transform(g,?,'EPSG:4326',always_xy:=true))
            FROM (SELECT ST_CollectionExtract(ST_Difference(
                ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true),
                COALESCE(ST_GeomFromWKB(?),ST_GeomFromText('POLYGON EMPTY'))),3) g)''',
            [crs,geo,crs,context_masks.get(rpc)]).fetchone()
        return result
    tier_regions = {}
    for rpc,geo in regional_unions(tier_lookup.values()).items():
        area,clipped = clip_tier_geometry(geo,rpc)
        if area>0:
            tier_regions[rpc] = clipped
    flu_failures = [item for item in municipal['audit']['unassigned_parts']
                   if (item.get('source_index'),item.get('part')) not in context_excluded]
    incomplete_flu = {sources[x['source_index']]['rpc'] for x in flu_failures}
    # Unknown FLU codes and missing geometry in any selected FLU can hide a housing block.
    incomplete_flu.update(row[5] for row in all_rows if row[6] == selected[row[5]]
                          and (row[10] is None
                               or (row[10] in config.HOUSING_RULES['categories'] and row[9] is None)))
    tier_sources = tier['audit']['sources']
    tier_dates = dict(con.execute("SELECT feature_id,max(date_lurb) FROM map_features WHERE kind='tier' GROUP BY feature_id").fetchall())
    for source in tier_sources:
        source['date_lurb'] = tier_dates.get(source['feature_id'])
    selected_tier_failures = [x for x in tier['audit']['unassigned_parts']
        if tier_sources[x['source_index']]['map_stage'] == tier_selected[tier_sources[x['source_index']]['rpc']]]
    tier_context_adjustments,remaining_tier_failures = [],[]
    for item in selected_tier_failures:
        if item.get('reason')!='no qualifying municipality' or 'geometry_wkb_hex' not in item:
            remaining_tier_failures.append(item)
            continue
        wkb = bytes.fromhex(item['geometry_wkb_hex'])
        valid,area = con.execute('SELECT ST_IsValid(g),ST_Area(g) FROM (SELECT ST_GeomFromWKB(?) g)',[wkb]).fetchone()
        if not valid or area<=0:
            remaining_tier_failures.append(item)
            continue
        tier_context_adjustments.append(dict(tier_source_indices=[item['source_index']],source_part=item['part'],
            geometry_sha256=hashlib.sha256(wkb).hexdigest(),original_area_m2=area,
            excluded_m2=area,residual_area_m2=0,
            reason='outside_municipality_assignment'))
    incomplete_tier = {tier_sources[x['source_index']]['rpc'] for x in remaining_tier_failures}
    def comparison(rpc,geoid):
        if rpc not in selected:
            return 'missing_flu'
        if rpc in incomplete_flu:
            return 'incomplete_flu'
        if rpc not in tier_selected:
            return 'missing_tier'
        if rpc in incomplete_tier:
            return 'incomplete_tier'
        if selected[rpc] != tier_selected[rpc]:
            return 'stage_mismatch'
        return 'comparable'
    blocks,coverage_parts = [],[]
    housing_lookup = {}
    for feature in municipal['areas']['features']:
        props = feature['properties']
        rpc,geoid = props['rpc'],props['geoid']
        housing_lookup[(rpc,geoid)] = feature
        # Regional unions prevent different municipal ownership of protrusions from
        # manufacturing uncovered borders. Both inputs still follow assignment rules.
        tier_geo = tier_regions.get(rpc)
        con.execute('''CREATE OR REPLACE TEMP TABLE block_input AS SELECT
            ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true) g''',
            [json.dumps(feature['geometry']),crs])
        # Group across narrow road gaps, retaining the actual unbuffered area.
        # A group can therefore remain a MultiPolygon; no new housing land is added.
        parts = con.execute('''SELECT ST_AsWKB(shape),ST_Area(shape),ST_AsGeoJSON(
            ST_Transform(shape,?,'EPSG:4326',always_xy:=true)) FROM
            (SELECT ST_CollectionExtract(ST_Intersection(g,piece.geom),3) shape
             FROM block_input,unnest(ST_Dump(ST_Buffer(g,?))) pieces(piece))
            ORDER BY ST_XMin(shape),ST_YMin(shape),ST_Area(shape)''',
            [crs,config.HOUSING_RULES['grouping_gap_m']/2]).fetchall()
        for index,(wkb,area,geo) in enumerate(parts):
            exact_covered,portions = split_housing_block(con,wkb,tier_geo,crs)
            covered = sum(area for kind,area,_ in portions if kind=='covered')
            covered = max(0,min(area,covered))
            indices = [r[0] for r in con.execute('''SELECT DISTINCT source_index FROM housing_assigned
                WHERE rpc=? AND geoid=? AND ST_Area(ST_Intersection(g,ST_GeomFromWKB(?)))>0
                ORDER BY source_index''',[rpc,geoid,wkb]).fetchall()]
            tier_indices = [r[0] for r in con.execute('''SELECT DISTINCT source_index FROM assigned
                WHERE rpc=? AND stage=? AND ST_Area(ST_Intersection(g,ST_GeomFromWKB(?)))>0
                ORDER BY source_index''',[rpc,tier_selected.get(rpc),wkb]).fetchall()]
            state = comparison(rpc,geoid)
            block_id = f'{rpc}:{geoid}:{props["map_stage"]}:{index}'
            block_props = dict(block_id=block_id,geoid=geoid,municipality=props['municipality'],
                    rpc=rpc,map_stage=props['map_stage'],tier_map_stage=tier_selected.get(rpc),
                    source_indices=indices,tier_source_indices=tier_indices,
                    area_m2=area,covered_m2=covered,exact_covered_m2=exact_covered,
                    coverage_fraction=covered/area,
                    comparison_status=state,coverage_status=housing_coverage(area,covered) if state=='comparable' else 'unknown')
            blocks.append({'type':'Feature','id':block_id,'geometry':json.loads(geo),'properties':block_props})
            display_portions = portions if state=='comparable' else [('unknown',area,json.loads(geo))]
            for kind,portion_area,portion_geo in display_portions:
                coverage_parts.append({'type':'Feature','id':f'{block_id}:{kind}',
                    'geometry':portion_geo,'properties':{**block_props,'coverage_kind':kind,
                                                        'portion_area_m2':portion_area}})
    summaries = []
    for geoid,name,_ in towns:
        matches = con.execute('''SELECT DISTINCT r.rpc FROM municipal_boundaries t JOIN rpc_boundaries r
            ON ST_Intersects(ST_PointOnSurface(t.geom),r.geom) WHERE t.geoid=? ORDER BY r.rpc''',[geoid]).fetchall()
        if len(matches)!=1:
            raise ValueError(f'Ambiguous RPC membership for housing summary: {name}')
        rpc = matches[0][0]
        local = [b['properties'] for b in blocks if b['properties']['geoid']==geoid]
        counts = {status:sum(b['coverage_status']==status for b in local)
                  for status in ('substantial','partial','none','unknown')}
        area = sum(b['area_m2'] for b in local)
        covered = sum(b['covered_m2'] for b in local)
        state = comparison(rpc,geoid)
        flu_complete = rpc in selected and rpc not in incomplete_flu
        status = ('no_housing' if not local and flu_complete else
                  'unknown' if state!='comparable' or counts['unknown'] else
                  'all' if counts['substantial']==len(local) else
                  'none' if counts['none']==len(local) else 'some')
        summaries.append(dict(geoid=geoid,municipality=name,rpc=rpc,status=status,
            block_count=len(local),substantial_count=counts['substantial'],partial_count=counts['partial'],
            none_count=counts['none'],unknown_count=counts['unknown'],area_m2=area,covered_m2=covered,
            coverage_fraction=covered/area if area else None,comparison_status=state,
            map_stage=selected.get(rpc),tier_map_stage=tier_selected.get(rpc)))
    outside, diagnostics = [], []
    for (rpc,geoid),feature in sorted(tier_lookup.items()):
        display_area = feature['properties']['area_m2']
        area,tier_geo = clip_tier_geometry(json.dumps(feature['geometry']),rpc)
        housing_geo = housing_regions.get(rpc)
        result = con.execute('''SELECT ST_Area(g),ST_AsGeoJSON(ST_Transform(g,?,'EPSG:4326',always_xy:=true))
            FROM (SELECT ST_CollectionExtract(ST_Difference(
                ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true),
                COALESCE(ST_Transform(ST_GeomFromGeoJSON(?),'EPSG:4326',?,always_xy:=true),
                ST_GeomFromText('POLYGON EMPTY'))),3) g)''', [crs,tier_geo,crs,housing_geo,crs]).fetchone()
        meaningful = result[0] > max(area*config.HOUSING_RULES['reverse_near_complete_fraction'],
                                    min(area*config.HOUSING_RULES['reverse_tolerance_fraction'],
                                        config.HOUSING_RULES['reverse_tolerance_m2']))
        props = dict(geoid=geoid,municipality=feature['properties']['municipality'],rpc=rpc,
            map_stage=tier_selected[rpc],flu_map_stage=selected.get(rpc),tier_area_m2=area,
            tier_source_indices=feature['properties']['source_indices'],
            display_tier_area_m2=display_area,analytical_excluded_m2=max(0,display_area-area),
            outside_m2=result[0],outside_fraction=result[0]/area if area else None,meaningful=meaningful,
            comparison_status=comparison(rpc,geoid))
        diagnostics.append(props)
        if meaningful:
            outside.append({'type':'Feature','id':f'{rpc}:{geoid}:outside','properties':props,
                            'geometry':json.loads(result[1])})
    sensitivity = []
    for near_complete,fraction,absolute in ((0,0.01,250),(0.01,0.05,1000),(0.02,0.1,2500)):
        settings = {**config.HOUSING_RULES,'coverage_tolerance_fraction':fraction,
                    'coverage_tolerance_m2':absolute,'coverage_near_complete_fraction':near_complete}
        comparable = [b['properties'] for b in blocks if b['properties']['comparison_status']=='comparable']
        counts = {s:sum(housing_coverage(b['area_m2'],b['covered_m2'],settings)==s for b in comparable)
                  for s in ('substantial','partial','none')}
        changed = [b['block_id'] for b in comparable
                   if housing_coverage(b['area_m2'],b['covered_m2'],settings)!=b['coverage_status']]
        municipal_counts = {'all':0,'some':0,'none':0}
        changed_towns = []
        for town in summaries:
            if town['status'] not in municipal_counts:
                continue
            local = [b for b in comparable if b['geoid']==town['geoid']]
            statuses = [housing_coverage(b['area_m2'],b['covered_m2'],settings) for b in local]
            result = 'all' if all(s=='substantial' for s in statuses) else 'none' if all(s=='none' for s in statuses) else 'some'
            municipal_counts[result] += 1
            if result != town['status']:
                changed_towns.append(town['municipality'])
        sensitivity.append(dict(near_complete_fraction=near_complete,fraction=fraction,
                                absolute_m2=absolute,counts=counts,changed_block_ids=changed,
                                municipality_counts=municipal_counts,changed_municipalities=changed_towns))
    return {**stamp,'selected_stages':selected,'tier_selected_stages':tier_selected,
        'sources':sources,'tier_sources':tier_sources,'categories':{'type':'FeatureCollection','features':categories},
        'context_fragments':{'type':'FeatureCollection','features':context_features},
        'blocks':{'type':'FeatureCollection','features':blocks},'municipalities':summaries,
        'coverage_parts':{'type':'FeatureCollection','features':coverage_parts},
        'tier_outside':{'type':'FeatureCollection','features':outside},'reverse_diagnostics':diagnostics,
        'sensitivity':sensitivity,'audit':municipal['audit'],
        'boundary_context':{'basis':'existing municipality interior qualification',
            'flu_excluded_count':len(context_features),
            'flu_excluded_m2':sum(f['properties']['area_m2'] for f in context_features),
            'tier_adjustments':tier_context_adjustments},
        'uncertainty':{'incomplete_flu_rpcs':sorted(incomplete_flu),
                       'incomplete_tier_rpcs':sorted(incomplete_tier),
                       'incomplete_flu_municipalities':[],
                       'incomplete_tier_municipalities':[]}}


def load_housing_growth(con, path=config.HOUSING_PATH):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Missing housing growth preparation; run make prepare.')
    document = json.loads(path.read_text())
    stamp,_,_ = housing_inputs(con)
    if any(document.get(k)!=v for k,v in stamp.items()):
        raise ValueError('Stale housing growth preparation; run make prepare.')
    return document


def prepare_housing_growth(db_path=DB_PATH, output=None, force=False):
    output = Path(output) if output else Path(db_path).parent/'housing-growth.json'
    if not Path(db_path).is_file():
        raise ValueError('Restore the saved database first')
    with duckdb.connect(str(db_path),read_only=True) as con:
        con.execute('LOAD spatial')
        con.execute('BEGIN TRANSACTION')
        stamp,_,_ = housing_inputs(con)
        if output.is_file() and not force:
            saved = json.loads(output.read_text())
            if all(saved.get(k)==v for k,v in stamp.items()):
                return
        document = derive_housing_growth(con)
        con.execute('COMMIT')
    write_json(output,document)
    print(f'Prepared {len(document["blocks"]["features"])} housing growth blocks → {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot', type=Path, help='Load this completed raw snapshot')
    source.add_argument('--prepare', action='store_true', help='Prepare relationships from the existing read-only database')
    parser.add_argument('--db', type=Path, default=DB_PATH)
    parser.add_argument('--memberships', type=Path, default=MEMBERSHIP_PATH)
    parser.add_argument('--force', action='store_true', help='Recompute spatial sidecars even when input fingerprints match')
    args = parser.parse_args()
    if args.snapshot:
        load_snapshot(args.snapshot, args.db)
    prepare(args.db, args.memberships)
    prepare_tier(args.db, force=args.force)
    prepare_housing_growth(args.db, force=args.force)


if __name__ == '__main__':
    main()
