import json
import os
import tempfile
from datetime import datetime, timezone

import duckdb

import config


def is_windham_orphan(props):
    if (props.get("RPC") or "").strip() != "":
        return False
    if (props.get("TIER_VERS") or "").strip() != "":
        return False
    if (props.get("SUBMITTER") or "").strip() != "":
        return False
    if (props.get("TIER_AREA") or "").strip() != "1B":
        return False
    creator = (props.get("Creator") or "").strip().lower()
    if not creator.startswith("wrcgis"):
        return False
    return True


def clean_val(val, target_field=None):
    if val is None:
        return None
    if isinstance(val, (int, float)) and val > 1000000000000:
        try:
            return datetime.fromtimestamp(val / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        except Exception:
            return None
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        if val in config.VERSION_NORMALIZE:
            return config.VERSION_NORMALIZE[val]
        if val in config.RPC_NAME_TO_CODE:
            return config.RPC_NAME_TO_CODE[val]
        if target_field in ("flu_code", "tier_code") and val in config.FLU_NAME_TO_CODE:
            return config.FLU_NAME_TO_CODE[val]
    return val


def load_geojson(path):
    with open(path) as f:
        data = json.load(f)
    return data.get("features", [])


def build_flu_rows(source_key, features, field_map):
    rows = []
    for feat in features:
        geom = feat.get("geometry")
        if not geom or not geom.get("type"):
            continue
        props = feat.get("properties") or {}
        oid = props.get("OBJECTID", props.get("FID", 0))
        row = {
            "id": f"{source_key}::{oid}",
            "geom_json": json.dumps(geom),
            "source_layer": source_key,
        }
        for src_field, tgt_field in field_map.items():
            if tgt_field is None:
                continue
            if tgt_field == "source_oid":
                row[tgt_field] = props.get(src_field)
            else:
                val = props.get(src_field)
                if isinstance(val, str):
                    val = val.strip() or None
                row[tgt_field] = clean_val(val, tgt_field) if val is not None else None
        if row.get("version") is None and source_key.endswith("_pre"):
            row["version"] = "PRE"
        for c in config.FLU_COLUMNS:
            if c not in row and c != "geom":
                row[c] = None
        rows.append(row)
    return rows


def build_tier_rows(source_key, features, field_map):
    rows = []
    windham_repaired = 0
    for feat in features:
        geom = feat.get("geometry")
        if not geom or not geom.get("type"):
            continue
        props = feat.get("properties") or {}
        is_orphan = False
        if source_key == "tier_consolidated" and is_windham_orphan(props):
            props = dict(props)
            props["RPC"] = "WR"
            props["TIER_VERS"] = None
            props["SUBMITTER"] = None
            is_orphan = True
            windham_repaired += 1
        oid = props.get("OBJECTID", props.get("FID", 0))
        row = {
            "id": f"{source_key}::{oid}",
            "geom_json": json.dumps(geom),
            "source_layer": source_key,
        }
        for src_field, tgt_field in field_map.items():
            if tgt_field is None:
                continue
            if tgt_field == "source_oid":
                row[tgt_field] = props.get(src_field)
            else:
                val = props.get(src_field)
                if isinstance(val, str):
                    val = val.strip() or None
                row[tgt_field] = clean_val(val, tgt_field) if val is not None else None
        if is_orphan:
            row["rpc"] = "WR"
            row["version"] = None
            row["submitter"] = None
            notes_val = (props.get("NOTES") or "")
            if notes_val in config.WINDHAM_TOWNS:
                row["notes"] = notes_val
        if source_key in config.TIER1B_SOURCES:
            row["tier_code"] = "1B"
        if row.get("version") is None and source_key.endswith("_pre"):
            row["version"] = "PRE"
        for c in config.TIER_COLUMNS:
            if c not in row and c != "geom":
                row[c] = None
        rows.append(row)
    if windham_repaired:
        print(f"  Repaired {windham_repaired} Windham orphan features")
    return rows


def build_boundary_rows(source_key, features, field_map):
    boundary_type = "unknown"
    for suffix, bt in config.BOUNDARY_TYPE_MAP.items():
        if source_key.endswith(suffix):
            boundary_type = bt
            break
    rows = []
    for feat in features:
        geom = feat.get("geometry")
        if not geom or not geom.get("type"):
            continue
        props = feat.get("properties") or {}
        oid = props.get("OBJECTID", 0)
        row = {
            "id": f"{source_key}::{oid}",
            "geom_json": json.dumps(geom),
            "boundary_type": boundary_type,
            "source_layer": source_key,
        }
        for src_field, tgt_field in field_map.items():
            if tgt_field is None:
                continue
            if tgt_field == "source_oid":
                row[tgt_field] = props.get(src_field)
            else:
                val = props.get(src_field)
                if isinstance(val, str):
                    val = val.strip() or None
                row[tgt_field] = val
        for c in config.BOUNDARY_COLUMNS:
            if c not in row and c != "geom":
                row[c] = None
        rows.append(row)
    return rows


def build_population_rows(source_key, features, field_map):
    rows = []
    for feat in features:
        props = feat.get("properties") or {}
        oid = props.get("OBJECTID", 0)
        row = {
            "id": f"{source_key}::{oid}",
            "source_layer": source_key,
        }
        for src_field, tgt_field in field_map.items():
            if tgt_field is None:
                continue
            if tgt_field == "source_oid":
                row[tgt_field] = props.get(src_field)
            else:
                val = props.get(src_field)
                if isinstance(val, str):
                    val = val.strip() or None
                row[tgt_field] = val
        for c in config.POPULATION_COLUMNS:
            if c not in row:
                row[c] = None
        rows.append(row)
    return rows


def build_water_rows(source_key, features, field_map):
    rows = []
    for feat in features:
        geom = feat.get("geometry")
        if not geom or not geom.get("type"):
            continue
        props = feat.get("properties") or {}
        oid = props.get("OBJECTID", 0)
        row = {
            "id": f"{source_key}::{oid}",
            "geom_json": json.dumps(geom),
            "source_layer": source_key,
        }
        for src_field, tgt_field in field_map.items():
            if tgt_field is None:
                continue
            if tgt_field == "source_oid":
                row[tgt_field] = props.get(src_field)
            else:
                val = props.get(src_field)
                if isinstance(val, str):
                    val = val.strip() or None
                row[tgt_field] = val
        for c in config.WATER_COLUMNS:
            if c not in row and c != "geom":
                row[c] = None
        rows.append(row)
    return rows


def bulk_load(duck, rows, table, columns):
    if not rows:
        return 0
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(rows, tmp)
    tmp.close()
    select_parts = []
    for c in columns:
        if c == "geom":
            select_parts.append("ST_GeomFromGeoJSON(geom_json)")
        else:
            select_parts.append(c)
    col_list = ", ".join(columns)
    sel = ", ".join(select_parts)
    duck.execute(f"""
        INSERT INTO {table} ({col_list})
        SELECT {sel}
        FROM read_json_auto('{tmp.name}', maximum_object_size=500000000)
    """)
    os.unlink(tmp.name)
    return len(rows)


CREATE_TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS flu_areas (
        id VARCHAR, geom GEOMETRY, flu_code VARCHAR, name VARCHAR,
        rpc VARCHAR, version VARCHAR, submitter VARCHAR, geoid VARCHAR,
        desig_center_step VARCHAR, desig_type VARCHAR, lurb_status VARCHAR,
        date_rpc VARCHAR, date_lurb VARCHAR, date_agg VARCHAR, notes VARCHAR,
        lu_auth VARCHAR, source_layer VARCHAR, source_oid BIGINT
    )""",
    """CREATE TABLE IF NOT EXISTS tier_areas (
        id VARCHAR, geom GEOMETRY, tier_code VARCHAR,
        rpc VARCHAR, version VARCHAR, submitter VARCHAR, geoid VARCHAR,
        lurb_status VARCHAR, date_subm VARCHAR, date_lurb VARCHAR,
        date_agg VARCHAR, notes VARCHAR, source_layer VARCHAR, source_oid BIGINT
    )""",
    """CREATE TABLE IF NOT EXISTS boundary_areas (
        id VARCHAR, geom GEOMETRY, boundary_type VARCHAR,
        name VARCHAR, geoid VARCHAR, rpc_code VARCHAR, source_layer VARCHAR,
        source_oid BIGINT
    )""",
    """CREATE TABLE IF NOT EXISTS water_areas (
        id VARCHAR, geom GEOMETRY, source_name VARCHAR, wbid VARCHAR,
        lakeid VARCHAR, event_type VARCHAR, gis_acres DOUBLE,
        source_layer VARCHAR, source_oid BIGINT
    )""",
    """CREATE TABLE IF NOT EXISTS population (
        id VARCHAR, geoid VARCHAR, name VARCHAR,
        total_pop BIGINT, pop_18_over BIGINT,
        housing_units BIGINT, occupied_housing BIGINT,
        source_layer VARCHAR, source_oid BIGINT
    )""",
]

MATERIALIZATION_SQL = [
    # Per-RPC unions
    """CREATE TABLE rpc_growth_union AS
       SELECT rpc, ST_Union_Agg(geom) AS geom
       FROM flu_areas
       WHERE flu_code IN ('DC','VC','VA','PGA') AND rpc IS NOT NULL AND rpc != ''
       GROUP BY rpc""",
    """CREATE TABLE rpc_tier_union AS
       SELECT rpc, version, ST_Union_Agg(geom) AS geom
       FROM tier_areas
       WHERE tier_code = '1B' AND rpc IS NOT NULL AND rpc != ''
       GROUP BY rpc, version""",
    """CREATE TABLE rpc_tier_any AS
       SELECT rpc, ST_Union_Agg(geom) AS geom
       FROM rpc_tier_union
       GROUP BY rpc""",
    # Statewide unions (from per-RPC unions where possible)
    """CREATE TABLE statewide_growth AS
       SELECT ST_Union_Agg(geom) AS geom FROM rpc_growth_union""",
    """CREATE TABLE statewide_tier AS
       SELECT ST_Union_Agg(geom) AS geom FROM tier_areas WHERE tier_code = '1B'""",
    """CREATE TABLE statewide_pre AS
       SELECT ST_Union_Agg(geom) AS geom FROM rpc_tier_union WHERE version = 'PRE'""",
    """CREATE TABLE statewide_app AS
       SELECT ST_Union_Agg(geom) AS geom FROM rpc_tier_union WHERE version = 'APP'""",
    # Per-FLU-code unions
    """CREATE TABLE flu_code_unions AS
       SELECT flu_code, ST_Union_Agg(geom) AS geom
       FROM flu_areas
       WHERE flu_code IN ('DC','VC','VA','PGA')
       GROUP BY flu_code""",
    # Water unions
    """CREATE TABLE statewide_water AS
       SELECT ST_Union_Agg(geom) AS geom FROM water_areas""",
    """CREATE TABLE statewide_tier_water AS
       SELECT ST_CollectionExtract(ST_Intersection(t.geom, w.geom), 3) AS geom
       FROM statewide_tier t, statewide_water w""",
    """CREATE TABLE statewide_growth_water AS
       SELECT ST_CollectionExtract(ST_Intersection(g.geom, w.geom), 3) AS geom
       FROM statewide_growth g, statewide_water w""",
    """CREATE TABLE statewide_pre_water AS
       SELECT ST_CollectionExtract(ST_Intersection(t.geom, w.geom), 3) AS geom
       FROM statewide_pre t, statewide_water w""",
    """CREATE TABLE statewide_app_water AS
       SELECT ST_CollectionExtract(ST_Intersection(t.geom, w.geom), 3) AS geom
       FROM statewide_app t, statewide_water w""",
]

PRE_INTERSECT_SQL = [
    # RPC stats: each RPC boundary intersected with growth/pre/app statewide unions
    """CREATE TABLE rpc_stats_data AS
       SELECT r.name, r.rpc_code, r.geom AS rpc_geom,
              ST_Intersection(r.geom, g.geom) AS growth_geom,
              ST_Intersection(r.geom, p.geom) AS pre_geom,
              ST_Intersection(r.geom, a.geom) AS app_geom,
              ST_CollectionExtract(ST_Intersection(r.geom, w.geom), 3) AS rpc_water_geom,
              ST_CollectionExtract(ST_Intersection(r.geom, gw.geom), 3) AS growth_water_geom,
              ST_CollectionExtract(ST_Intersection(r.geom, pw.geom), 3) AS pre_water_geom,
              ST_CollectionExtract(ST_Intersection(r.geom, aw.geom), 3) AS app_water_geom
       FROM boundary_areas r, statewide_growth g, statewide_pre p, statewide_app a,
            statewide_water w, statewide_growth_water gw, statewide_pre_water pw, statewide_app_water aw
       WHERE r.boundary_type = 'rpc'""",
    # FLU-tier stats: each FLU code intersected with tier union
    """CREATE TABLE flu_tier_data AS
       SELECT f.flu_code, f.geom AS total_geom,
              COALESCE(ST_Intersection(f.geom, t.geom),
                       ST_GeomFromText('GEOMETRYCOLLECTION EMPTY')) AS overlap_geom,
              ST_CollectionExtract(ST_Intersection(f.geom, w.geom), 3) AS total_water_geom,
              ST_CollectionExtract(ST_Intersection(ST_Intersection(f.geom, t.geom), w.geom), 3) AS overlap_water_geom
       FROM flu_code_unions f, statewide_tier t, statewide_water w
       UNION ALL
       SELECT 'ALL', g.geom,
              COALESCE(ST_Intersection(g.geom, t.geom),
                       ST_GeomFromText('GEOMETRYCOLLECTION EMPTY')),
              ST_CollectionExtract(ST_Intersection(g.geom, w.geom), 3),
              ST_CollectionExtract(ST_Intersection(ST_Intersection(g.geom, t.geom), w.geom), 3)
       FROM statewide_growth g, statewide_tier t, statewide_water w""",
    # Town-tier-water stats: per-town tier overlap and water intersections
    """CREATE TABLE town_tier_stats_data AS
       SELECT b.name, b.geoid,
              b.geom AS town_geom,
              ST_CollectionExtract(ST_Intersection(b.geom, st.geom), 3) AS tier_overlap_geom,
              ST_CollectionExtract(ST_Intersection(b.geom, w.geom), 3) AS water_geom,
              ST_CollectionExtract(ST_Intersection(b.geom, tw.geom), 3) AS tier_water_geom
       FROM boundary_areas b, statewide_tier st, statewide_water w, statewide_tier_water tw
       WHERE b.boundary_type = 'town'""",
    # Full overlay: per-RPC growth split by tier status
    """CREATE TABLE overlay_results AS
       WITH rpc_app_overlap AS (
           SELECT g.rpc, ST_Intersection(g.geom, a.geom) AS geom
           FROM rpc_growth_union g
           JOIN rpc_tier_union a ON a.rpc = g.rpc AND a.version = 'APP'
       ),
       rpc_pre_overlap AS (
           SELECT g.rpc,
               CASE WHEN a.rpc IS NOT NULL
                   THEN ST_Difference(ST_Intersection(g.geom, p.geom), a.geom)
                   ELSE ST_Intersection(g.geom, p.geom)
               END AS geom
           FROM rpc_growth_union g
           JOIN rpc_tier_union p ON p.rpc = g.rpc AND p.version = 'PRE'
           LEFT JOIN rpc_tier_union a ON a.rpc = g.rpc AND a.version = 'APP'
       ),
       rpc_no_tier AS (
           SELECT g.rpc,
               ST_Difference(g.geom, COALESCE(ta.geom, ST_GeomFromText('MULTIPOLYGON EMPTY'))) AS geom
           FROM rpc_growth_union g
           LEFT JOIN rpc_tier_any ta ON ta.rpc = g.rpc
       )
       SELECT g.rpc, g.geom AS growth_geom,
              ao.geom AS app_overlap_geom,
              po.geom AS pre_overlap_geom,
              no.geom AS no_tier_geom
       FROM rpc_growth_union g
       LEFT JOIN rpc_app_overlap ao ON ao.rpc = g.rpc
       LEFT JOIN rpc_pre_overlap po ON po.rpc = g.rpc
       LEFT JOIN rpc_no_tier no ON no.rpc = g.rpc""",
]


def main():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    if config.DB_PATH.exists():
        config.DB_PATH.unlink()

    duck = duckdb.connect(str(config.DB_PATH))
    duck.execute("LOAD spatial;")

    for ddl in CREATE_TABLES_SQL:
        duck.execute(ddl)

    # ── Ingest GeoJSON sources ──
    print("── Ingesting GeoJSON sources ──")
    for source_key, source_cfg in config.SOURCES.items():
        path = config.IN_DIR / f"{source_key}.geojson"
        if not path.exists():
            print(f"SKIP {source_key} — no file at {path}")
            continue

        domain = source_cfg["domain"]
        field_map = config.FIELD_MAPS[source_key]
        features = load_geojson(path)

        if domain == "flu":
            rows = build_flu_rows(source_key, features, field_map)
            n = bulk_load(duck, rows, "flu_areas", config.FLU_COLUMNS)
            print(f"  {source_key}: {n} flu_areas rows")
        elif domain == "tier":
            rows = build_tier_rows(source_key, features, field_map)
            n = bulk_load(duck, rows, "tier_areas", config.TIER_COLUMNS)
            print(f"  {source_key}: {n} tier_areas rows")
        elif domain == "boundary":
            rows = build_boundary_rows(source_key, features, field_map)
            n = bulk_load(duck, rows, "boundary_areas", config.BOUNDARY_COLUMNS)
            print(f"  {source_key}: {n} boundary_areas rows")
        elif domain == "water":
            rows = build_water_rows(source_key, features, field_map)
            n = bulk_load(duck, rows, "water_areas", config.WATER_COLUMNS)
            print(f"  {source_key}: {n} water_areas rows")
        elif domain == "population":
            rows = build_population_rows(source_key, features, field_map)
            n = bulk_load(duck, rows, "population", config.POPULATION_COLUMNS)
            print(f"  {source_key}: {n} population rows")

    flu_count = duck.execute("SELECT COUNT(*) FROM flu_areas").fetchone()[0]
    tier_count = duck.execute("SELECT COUNT(*) FROM tier_areas").fetchone()[0]
    repair_count = duck.execute(
        "SELECT COUNT(*) FROM tier_areas WHERE source_layer = 'tier_consolidated' AND rpc = 'WR' AND version IS NULL"
    ).fetchone()[0]
    boundary_count = duck.execute("SELECT COUNT(*) FROM boundary_areas").fetchone()[0]
    water_count = duck.execute("SELECT COUNT(*) FROM water_areas").fetchone()[0]
    print(f"\nSummary: {flu_count} flu areas, {tier_count} tier areas ({repair_count} WR repaired)")
    print(f"         {boundary_count} boundary areas, {water_count} water areas")

    # ── Validate geometries ──
    print("\n── Validating geometries ──")
    for table in ["flu_areas", "tier_areas"]:
        invalid = duck.execute(f"SELECT COUNT(*) FROM {table} WHERE NOT ST_IsValid(geom)").fetchone()[0]
        if invalid > 0:
            duck.execute(f"UPDATE {table} SET geom = ST_Buffer(geom, 0) WHERE NOT ST_IsValid(geom)")
            remaining = duck.execute(f"SELECT COUNT(*) FROM {table} WHERE NOT ST_IsValid(geom)").fetchone()[0]
            if remaining > 0:
                duck.execute(f"UPDATE {table} SET geom = ST_CollectionExtract(ST_MakeValid(geom), 3) WHERE NOT ST_IsValid(geom)")
            print(f"  Fixed {invalid} invalid geometries in {table}")

    # ── Create spatial indexes ──
    print("\n── Creating spatial indexes ──")
    duck.execute("CREATE INDEX idx_flu_geom ON flu_areas (geom)")
    duck.execute("CREATE INDEX idx_tier_geom ON tier_areas (geom)")
    duck.execute("CREATE INDEX idx_boundary_geom ON boundary_areas (geom)")
    print("  Created R-tree indexes on all geometry columns")

    # ── Materialize aggregated layers ──
    print("\n── Materializing aggregated layers ──")
    for sql in MATERIALIZATION_SQL:
        table_name = sql.split("CREATE TABLE ")[1].split(" AS")[0]
        duck.execute(sql)
        count = duck.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"  {table_name}: {count} rows")

    # ── Pre-intersect analysis results ──
    print("\n── Pre-intersecting analysis results ──")
    for sql in PRE_INTERSECT_SQL:
        table_name = sql.split("CREATE TABLE ")[1].split(" AS")[0]
        duck.execute(sql)
        count = duck.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"  {table_name}: {count} rows")

    duck.close()

    db_size = config.DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\nWrote {config.DB_PATH} ({db_size:.0f} MB)")


if __name__ == "__main__":
    main()
