# Vermont Act 181 — Future Land Use and Tier 1B Analysis

Analyzes the spatial overlap between Act 181 growth areas (Downtown Center, Village Center, Village Area, Planned Growth Area) and proposed/approved Tier 1B designations across Vermont's 11 Regional Planning Commissions.

## Pipeline

```
ArcGIS feature services ──→ extract.py ──→ in/*.geojson
                                       (raw schema, one per source)
in/*.geojson ──→ transform.py ──→ data/*.{db,parquet}
                           (field mapping, Windham repair,
                            version/RPC normalization,
                            FLU-shaped tier sources → tier_code="1B",
                            geometry validation,
                            Parquet via DuckDB spatial)
data/*.parquet ──→ analyze.py ──→ out/
                            (growth_tier_overlay.geojson,
                             index.html with Leaflet map)
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

All datasets are stored in two formats:

- **SQLite** (`data/act181.db`) — the original storage format, still written for backward compatibility
- **GeoParquet** (`data/*.parquet`) — geometry stored as DuckDB GEOMETRY type via the spatial extension, columnar format for fast I/O

The analyze step reads from Parquet via DuckDB, which uses R-tree spatial indexes and C-level spatial SQL (`ST_Union_Agg`, `ST_Intersection`, etc.) instead of loading every geometry into Python.

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
| `make transform` | Normalize all sources into `data/act181.db` + `data/*.parquet` |
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

## Dependencies

Python ≥3.9, `shapely`, `pyproj`, `duckdb`. Managed via `uv` — `duckdb` has a pure-Python wheel with no system requirements. The spatial extension is loaded at runtime via DuckDB's extension mechanism (`INSTALL spatial; LOAD spatial;`), no host-side install needed.
