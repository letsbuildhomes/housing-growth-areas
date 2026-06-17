import json
import sqlite3
from pathlib import Path

from shapely.geometry import shape
from shapely import to_wkb, from_wkb
from shapely.validation import make_valid

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


def repair_windham(props):
    props["RPC"] = "WR"
    props["TIER_VERS"] = None
    props["SUBMITTER"] = None
    return props


def load_geojson(path):
    with open(path) as f:
        data = json.load(f)
    return data.get("features", [])


def geom_to_wkb(feature):
    g = feature.get("geometry")
    if not g or not g.get("type"):
        return None
    try:
        geom = shape(g)
        if not geom.is_valid:
            geom = make_valid(geom)
        return to_wkb(geom, hex=True)
    except Exception:
        return None


def clean_val(val, target_field=None):
    if val is None:
        return None
    if isinstance(val, (int, float)) and val > 1000000000000:
        from datetime import datetime, timezone
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


def normalize_flu(features, source_key, field_map):
    rows = []
    for feat in features:
        props = feat.get("properties") or {}
        geom_wkb = geom_to_wkb(feat)
        if geom_wkb is None:
            continue
        row = {
            "id": f"{source_key}::{props.get('OBJECTID', props.get('FID', 0))}",
            "geometry": geom_wkb,
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
        rows.append(row)
    return rows


def normalize_tier(features, source_key, field_map):
    rows = []
    windham_repaired = 0
    for feat in features:
        props = feat.get("properties") or {}
        geom_wkb = geom_to_wkb(feat)
        if geom_wkb is None:
            continue

        is_orphan = False
        if source_key == "tier_consolidated" and is_windham_orphan(props):
            props = repair_windham(props)
            is_orphan = True
            windham_repaired += 1

        oid = props.get("OBJECTID", props.get("FID", 0))
        row = {
            "id": f"{source_key}::{oid}",
            "geometry": geom_wkb,
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

        if row.get("version") is None and source_key.endswith("_pre"):
            row["version"] = "PRE"

        if source_key in config.TIER1B_SOURCES:
            row["tier_code"] = "1B"

        rows.append(row)

    if windham_repaired:
        print(f"  Repaired {windham_repaired} Windham orphan features")
    return rows


def normalize_boundary(features, source_key, field_map):
    boundary_type = "unknown"
    for suffix, bt in config.BOUNDARY_TYPE_MAP.items():
        if source_key.endswith(suffix):
            boundary_type = bt
            break

    rows = []
    for feat in features:
        props = feat.get("properties") or {}
        geom_wkb = geom_to_wkb(feat)
        if geom_wkb is None:
            continue

        row = {
            "id": f"{source_key}::{props.get('OBJECTID', 0)}",
            "geometry": geom_wkb,
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
        rows.append(row)
    return rows


def write_parquet(rows, columns, geometry_col, parquet_path):
    if not rows:
        return
    duck = duckdb.connect()
    duck.execute("LOAD spatial;")
    col_list = [
        f'"{c}" BLOB' if c == geometry_col else f'"{c}" VARCHAR'
        for c in columns
    ]
    duck.execute(f"CREATE TABLE st ({', '.join(col_list)})")
    ph = ", ".join("?" for _ in columns)
    cn = ", ".join(f'"{c}"' for c in columns)
    data = [
        [bytes.fromhex(r[c]) if c == geometry_col and r.get(c) else r.get(c) for c in columns]
        for r in rows
    ]
    duck.executemany(f"INSERT INTO st ({cn}) VALUES ({ph})", data)
    sel = ", ".join(
        f'ST_GeomFromWKB("{c}") AS "{c}"' if c == geometry_col else f'"{c}"'
        for c in columns
    )
    duck.execute(f"COPY (SELECT {sel} FROM st) TO '{parquet_path}' (FORMAT PARQUET)")
    duck.close()


def write_rows(conn, rows, table, columns):
    placeholders = ", ".join("?" for _ in columns)
    col_names = ", ".join(columns)
    sql = f"INSERT OR REPLACE INTO {table} ({col_names}) VALUES ({placeholders})"
    with conn:
        for row in rows:
            vals = [row.get(c) for c in columns]
            conn.execute(sql, vals)


FLU_COLUMNS = [
    "id", "geometry", "flu_code", "name", "rpc", "version",
    "submitter", "geoid", "desig_center_step", "desig_type",
    "lurb_status", "date_rpc", "date_lurb", "date_agg", "notes",
    "lu_auth", "source_layer", "source_oid",
]

TIER_COLUMNS = [
    "id", "geometry", "tier_code", "rpc", "version",
    "submitter", "geoid", "lurb_status", "date_subm",
    "date_lurb", "date_agg", "notes", "source_layer", "source_oid",
]


def main():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")

    conn.execute(config.FLU_CREATE_SQL)
    conn.execute(config.TIER_CREATE_SQL)
    conn.execute(config.BOUNDARY_CREATE_SQL)

    all_flu_rows = []
    all_tier_rows = []
    boundary_rows = {"town": [], "county": [], "rpc": []}
    boundary_file_map = {
        "town": "boundary_towns",
        "county": "boundary_counties",
        "rpc": "boundary_rpcs",
    }

    for source_key in config.SOURCES:
        path = config.IN_DIR / f"{source_key}.geojson"
        if not path.exists():
            print(f"SKIP {source_key} — no file at {path}")
            continue

        domain = config.SOURCES[source_key]["domain"]
        field_map = config.FIELD_MAPS[source_key]
        features = load_geojson(path)
        print(f"LOAD {source_key}: {len(features)} features")

        if domain == "flu":
            rows = normalize_flu(features, source_key, field_map)
            write_rows(conn, rows, "flu_areas", FLU_COLUMNS)
            all_flu_rows.extend(rows)
            print(f"  → {len(rows)} flu_areas rows written")
        elif domain == "tier":
            rows = normalize_tier(features, source_key, field_map)
            write_rows(conn, rows, "tier_areas", TIER_COLUMNS)
            all_tier_rows.extend(rows)
            print(f"  → {len(rows)} tier_areas rows written")
        elif domain == "boundary":
            rows = normalize_boundary(features, source_key, field_map)
            write_rows(conn, rows, "boundary_areas", config.BOUNDARY_COLUMNS)
            for r in rows:
                boundary_rows[r["boundary_type"]].append(r)
            print(f"  → {len(rows)} boundary_areas rows written")

    flu_count = conn.execute("SELECT COUNT(*) FROM flu_areas").fetchone()[0]
    tier_count = conn.execute("SELECT COUNT(*) FROM tier_areas").fetchone()[0]
    repair_count = conn.execute(
        "SELECT COUNT(*) FROM tier_areas WHERE source_layer='tier_consolidated' AND rpc='WR' AND version IS NULL"
    ).fetchone()[0]
    print(f"\nSummary: {flu_count} flu areas, {tier_count} tier areas ({repair_count} WR repaired)")

    boundary_total = conn.execute("SELECT COUNT(*) FROM boundary_areas").fetchone()[0]
    print(f"         {boundary_total} boundary areas"
          + f" ({len(boundary_rows['town'])} towns, {len(boundary_rows['county'])} counties, {len(boundary_rows['rpc'])} rpcs)")

    conn.close()

    print("\n── Writing Parquet files ──")
    write_parquet(all_flu_rows, FLU_COLUMNS, "geometry",
                  str(config.PARQUET_DIR / "flu_areas.parquet"))
    print(f"  → data/flu_areas.parquet ({len(all_flu_rows)} rows)")
    write_parquet(all_tier_rows, TIER_COLUMNS, "geometry",
                  str(config.PARQUET_DIR / "tier_areas.parquet"))
    print(f"  → data/tier_areas.parquet ({len(all_tier_rows)} rows)")
    for bt, rows in boundary_rows.items():
        fname = boundary_file_map[bt]
        write_parquet(rows, config.BOUNDARY_COLUMNS, "geometry",
                      str(config.PARQUET_DIR / f"{fname}.parquet"))
        print(f"  → data/{fname}.parquet ({len(rows)} rows)")


if __name__ == "__main__":
    main()
