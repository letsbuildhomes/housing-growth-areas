# Vermont Act 181 — Future Land Use and Tier 1B Analysis

Analyzes the spatial overlap between Act 181 growth areas (Downtown Center, Village Center, Village Area, Planned Growth Area) and proposed/approved Tier 1B designations across Vermont's 11 Regional Planning Commissions.

## Pipeline

```
ArcGIS feature services ──→ extract.py ──→ in/*.geojson
                                       (raw schema, one per source)
in/*.geojson ──→ transform.py ──→ data/act181.duckdb
                           (bulk JSON ingestion via DuckDB,
                            field mapping, Windham repair,
                            version/RPC normalization,
                            FLU-shaped tier sources → tier_code="1B",
                            geometry validation,
                            R-tree indexes, materialized aggregates
                            and pre-intersected analysis results)
data/act181.duckdb ──→ analyze.py ──→ out/
                              (reads pre-materialized tables,
                               geodesic area via pyproj,
                               growth_tier_overlay.geojson
                               with per-RPC features,
                               index.html with Leaflet map
                               + boundary reference layers)
```

## Quick start

```bash
uv sync
make
# or step-by-step: make extract  →  make transform  →  make analyze
make serve   # opens out/index.html at http://localhost:8000
make status  # shows data coverage per RPC
```

## Data sources

13 ArcGIS feature services are queried:

### FLU and Tier

| Source | RPCs | Content |
|---|---|---|
| `flu_consolidated` | All 11 | FLU areas, PRE + APP versions (consolidated) |
| `tier_consolidated` | All 11 | Tier 1B areas, PRE + APP (includes 443 WR orphans) |
| `flu_nw_pre` | NW | NW pre-application FLU (not yet in consolidated) |
| `flu_rr_pre` | RR | RR pre-application FLU |
| `tier_nw_pre` | NW | NW pre-app Tier 1B (FLU-shaped → forced to tier) |
| `tier_rr_pre` | RR | RR pre-app Tier 1B |
| `tier_cc_pre` | CC | CC pre-app Tier 1B |
| `tier_ac_pre` | AC | AC pre-app Tier 1B |
| `tier_ma_pre` | MA | MA pre-app Tier 1B (has native TIER_AREA) |
| `tier_lc_pre` | LC | LC pre-app Tier 1B (has native TIER_AREA) |

### Boundaries (VCGI BNDHASH)

| Source | Features | Content |
|---|---|---|
| `boundary_towns` | 256 | Vermont town/municipal boundaries |
| `boundary_counties` | 14 | Vermont county boundaries |
| `boundary_rpcs` | 11 | Vermont Regional Planning Commission boundaries |

All three boundary layers come from VCGI's integrated BNDHASH dataset, which maintains vertically-integrated town/county/RPC boundaries. The `RPC` field in the RPC layer uses the same 2-letter codes as the rest of the pipeline.

Sources with `_pre` suffix are per-RPC pre-application services that haven't been merged into the consolidated public service yet.

## Storage format

Everything lives in a single DuckDB database: `data/act181.duckdb`.

The transform step reads GeoJSON features, writes them to temporary JSON files, and bulk-loads them into DuckDB using `read_json_auto` + `ST_GeomFromGeoJSON` in a single `INSERT...SELECT` per source. This avoids the memory leak that occurs with repeated `executemany` calls to `ST_GeomFromGeoJSON`.

All geometry columns use DuckDB's native `GEOMETRY` type (not the CRS-annotated variant), which enables R-tree spatial indexes. The spatial extension is loaded at runtime via `LOAD spatial;`.

### Raw tables

Three tables hold the ingested data, with R-tree indexes on their geometry columns:

- **`flu_areas`** — ~9,650 rows. Growth land use areas across 10 RPCs.
- **`tier_areas`** — ~860 rows. Tier 1B designations across 9 RPCs.
- **`boundary_areas`** — 281 rows. Town, county, and RPC boundaries from VCGI BNDHASH.

### Materialized aggregation tables

Pre-computed geometry unions, created once during transform:

| Table | Rows | Content |
|---|---|---|
| `rpc_growth_union` | 10 | Per-RPC union of growth areas (DC/VC/VA/PGA) |
| `rpc_tier_union` | ~15 | Per-RPC, per-version union of Tier 1B areas |
| `rpc_tier_any` | ~10 | Per-RPC union of all Tier 1B regardless of version |
| `statewide_growth` | 1 | Union of all growth areas statewide |
| `statewide_tier` | 1 | Union of all Tier 1B statewide |
| `statewide_pre` | 1 | Union of pre-app Tier 1B statewide |
| `statewide_app` | 1 | Union of final-app Tier 1B statewide |
| `flu_code_unions` | 4 | Statewide union per FLU code (DC/VC/VA/PGA) |

### Pre-intersected result tables

Analysis results computed once during transform, read in bulk by analyze.py:

| Table | Rows | Content |
|---|---|---|
| `overlay_results` | 10 | Per-RPC growth split into app-overlap, pre-overlap, and no-tier |
| `rpc_stats_data` | 11 | Each RPC boundary intersected with growth/pre/app statewide unions |
| `flu_tier_data` | 5 | Each FLU code + ALL intersected with tier union |

### Why materialize upfront

The expensive spatial operations — `ST_Union_Agg` over thousands of polygons, `ST_Intersection` of statewide unions against RPC boundaries — run once during transform (~20s) instead of on every analyze run. This makes analyze nearly instant (~1.5s) and keeps ad-hoc queries fast against the pre-computed tables.

## Normalized schemas

All tables store geometry with a `source_layer` + `source_oid` provenance chain back to the origin service.

**`flu_areas`** — ~9,650 records across 10 RPCs, 16 FLU codes.

| Column | Source |
|---|---|
| `flu_code` | DC, VC, VA, PGA, RAF, RC, ... (non-standard codes preserved: RD, WA, X) |
| `rpc` | Normalized to 2-letter code (AC, BC, CC, ...) |
| `version` | Normalized to PRE / APP |
| `geoid` | Town/village GEOID |
| `desig_center_step` | 1 (Beginner), 2 (Intermediate), 3 (Advanced) |
| `source_layer` | Which config source key this record came from |

**`tier_areas`** — ~860 records, all Tier 1B, across 9 RPCs.

| Column | Source |
|---|---|
| `tier_code` | 1B only |
| `rpc` | Normalized to 2-letter code |
| `version` | PRE / APP / NULL (443 Windham orphans have NULL) |
| `submitter` | RPC, MUNI, or LURB |
| `date_subm` | Date from submitter |

**`boundary_areas`** — 281 records across 3 types.

| Column | Source |
|---|---|
| `boundary_type` | `town`, `county`, or `rpc` |
| `name` | Town name, county name, or RPC short name |
| `geoid` | TOWNGEOID / CNTYGEOID / RPC code |
| `rpc_code` | RPC 2-letter code (only populated for RPC boundaries) |

## Windham orphan repair

443 features in `tier_consolidated` were bulk-imported by the WR GIS user with all metadata fields blank. The repair step identifies them by fingerprint (blank RPC + blank TIER_VERS + blank SUBMITTER + `TIER_AREA="1B"` + creator `wrcgis`) and assigns `RPC="WR"`. Version is left as NULL since it can't be determined.

## Key data notes

- **CV** (Central Vermont) has zero data — no FLU or Tier contributions in any source.
- **AC** has 50 Tier 1B pre-app features from their per-RPC service, but no APP data in consolidated.
- Several per-RPC "Tier 1B" services use FLU-area codes (DC, VC, VA, PGA) instead of tier codes. These are accepted as Tier 1B data with `tier_code="1B"` forced at load — the FLU code describes the growth category of the proposed area, not the tier designation.
- The tier/legend on the map lets you toggle between the three overlay categories (no tier, pre-app tier, final-app tier).

## Make targets

| Command | Action |
|---|---|
| `make` | extract → transform → analyze → status |
| `make extract` | Download fresh data from ArcGIS (skips cached files) |
| `make transform` | Ingest, validate, index, and materialize into `data/act181.duckdb` |
| `make analyze` | Generate overlay GeoJSON + Leaflet map (uses DuckDB spatial) |
| `make status` | Coverage table per RPC |
| `make clean` | Remove all generated artifacts |
| `make rebuild` | `make clean` + `make` |
| `make serve` | Serve `out/` on http://localhost:8000 |

## Adding new data sources

The map data evolves as RPCs submit new pre-application or final-application layers. Here's how to discover and add them.

### 1. Find new layer URLs

Open the [ArcGIS web experience](https://experience.arcgis.com/experience/58543fd6882d4bd6bd0b3008d98e874e/page/Main-Map-Page) in a browser. Open developer tools (F12) → Network tab, then interact with the map (pan, zoom, toggle layers). Look for requests to URLs containing `/FeatureServer/` — these are the feature services. The layer hierarchy (which RPC, which version, which data type) is visible in the webmap's layer list in the left panel.

Alternatively, the webmap JSON that powers the experience can be fetched directly — it lists every operational layer with its URL and definition expressions. The item ID is `509abf408c8a4e31964edefd997c1e84` (from `work/webmap_item.json`).

### 2. Determine the domain

Query the layer's metadata to see its fields:

```bash
# Replace URL with the new service
curl 'https://services.example.com/.../FeatureServer/0?f=json'
```

Look for these field names to decide if it goes into `flu_areas` or `tier_areas`:

| If it has | domain | table |
|---|---|---|
| `FLU_AREA`, `VERS_RPC`, `DESIG_CS` | `"flu"` | `flu_areas` |
| `TIER_AREA`, `TIER_VERS`, `SUBMITTER` | `"tier"` | `tier_areas` |
| `FLU_AREA` but NO `TIER_AREA` | `"tier"` with forced `tier_code="1B"` | `tier_areas` |

The third case is common for per-RPC pre-application services — they use FLU-shaped schemas but represent Tier 1B proposals. Add them with `domain: "tier"` and the source key to `TIER1B_SOURCES` in `config.py`.

### 3. Add the entry

Two places in `config.py`:

```python
# In SOURCES — pick a source_key like "{domain}_{rpc}_{version}"
"tier_ac_pre": {
    "url": "https://services8.arcgis.com/.../AC_TIER1B_PRE_poly_2026/FeatureServer/1",
    "domain": "tier",
},

# In FIELD_MAPS — map source field names to target column names
"tier_ac_pre": {
    "OBJECTID": "source_oid",
    "FLU_AREA": None,           # drop — domain="tier" with TIER1B_SOURCES forces "1B"
    "NAME": "name",
    "RPC": "rpc",
    "NOTES": "notes",
    "VERS_RPC": "version",
    "DATE_RPC": "date_subm",
},
```

For FLU-domain sources, map `FLU_AREA` → `flu_code`, `VERS_RPC` → `version`, etc. For tier-domain sources with a `TIER_AREA` field, map `TIER_AREA` → `tier_code`. For FLU-shaped tier sources (no `TIER_AREA`), set `FLU_AREA` → `None` and add the source key to `TIER1B_SOURCES` — the transform will set `tier_code="1B"` automatically.

### 4. Test

```bash
make clean && make
make status
```

Check the status table to confirm the new RPC's data appears in the right columns.

## Querying the database

The DuckDB database is self-contained and queryable interactively. The spatial extension loads automatically on connect.

```bash
duckdb data/act181.duckdb
```

### Ad-hoc spatial queries

The raw tables have R-tree indexes on their geometry columns, so spatial joins and filters are fast even without pre-materialization:

```sql
-- Growth areas that intersect Tier 1B in Chittenden County
SELECT f.id, f.flu_code, t.tier_code, t.version
FROM flu_areas f, tier_areas t
WHERE ST_Intersects(f.geom, t.geom)
  AND f.rpc = 'CC' AND f.flu_code = 'DC';

-- Growth areas within ~100m of any Tier 1B boundary
SELECT f.id, f.flu_code, f.rpc
FROM flu_areas f, tier_areas t
WHERE ST_DWithin(f.geom, t.geom, 0.001)
  AND f.flu_code IN ('DC','VC','VA','PGA');

-- How much growth area is within 500m of Tier 1B in a specific RPC?
SELECT SUM(ST_Area_Spheroid(ST_Intersection(f.geom, ST_Buffer(t.geom, 0.005)))) / 2589988.11
  AS growth_near_tier_sq_mi
FROM flu_areas f, tier_areas t
WHERE f.flu_code IN ('DC','VC','VA','PGA')
  AND f.rpc = 'CC' AND t.tier_code = '1B';
```

### Pre-materialized tables

For queries that match the pre-computed analysis, the materialized tables return instantly:

```sql
-- Full overlay results per RPC
SELECT rpc, ST_AsGeoJSON(growth_geom) FROM overlay_results;

-- RPC-level area statistics
SELECT name, rpc_code, ST_Area_Spheroid(growth_geom) / 2589988.11 AS growth_sq_mi
FROM rpc_stats_data;

-- FLU code breakdown
SELECT flu_code, ST_Area_Spheroid(overlap_geom) / 2589988.11 AS tier_sq_mi
FROM flu_tier_data;
```

### Note on area calculations

DuckDB's `ST_Area_Spheroid` returns incorrect values at Vermont latitudes (~41% of the true geodesic area). The analyze step uses pyproj's Karney geodesic algorithm for accurate area calculations. For ad-hoc queries where relative comparisons suffice, `ST_Area_Spheroid` still works — the error is consistent across features. For accurate absolute areas, extract the geometry as GeoJSON and compute with pyproj.

## Dependencies

Python ≥3.9, `pyproj`, `duckdb`. Managed via `uv` — `duckdb` has a pure-Python wheel with no system requirements. The spatial extension is loaded at runtime via DuckDB's extension mechanism (`INSTALL spatial; LOAD spatial;`), no host-side install needed.
