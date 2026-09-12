# Vermont Act 181 data ingest

Downloads the public interim exemption, future land use (FLU), Act 250 tier,
municipal-boundary, and Regional Planning Commission (RPC) boundary geometries
and attributes for Let's Build Homes. The default build exports the existing
database into a static dashboard. Downloading/ingesting is a separate, explicit
operation.

The current dashboard combines a Leaflet map above the interim-area
table. The map shows all interim polygons, municipality tint summaries, and RPC
boundaries; later pre-built views can add additional map datasets without
changing the ingest contract.

## Project guide

| Reference | What to find there |
|---|---|
| This README | Setup, daily commands, project layout, exports, and troubleshooting. |
| [DATA_DICTIONARY.md](DATA_DICTIONARY.md) | All current database tables/views and column meanings. |
| [SOURCE_INVENTORY.md](SOURCE_INVENTORY.md) | September 8, 2026 source counts, regional coverage, and known data irregularities. |
| [AGENTS.md](AGENTS.md) | Working conventions for future coding sessions. |
| [LEGACY_ANALYSIS.md](LEGACY_ANALYSIS.md) | Historical June overlay workflow; not the current dashboard. |

### Code and generated files

| Path | Role |
|---|---|
| `Makefile` | Default build, export, preview, tests, and explicit ingest commands. |
| `web/index.html` | Dashboard HTML template. |
| `web/dashboard.css` / `web/dashboard.js` | Styling, grouped table rendering, and browser filters. |
| `export_data.py` | Read-only database queries, grouping/sorting, and export registry. |
| `build_dashboard.py` | Embeds exports, CSS, and JS into standalone HTML. |
| `extract.py` | Current ingest command entry point; delegates to `ingest.py`. |
| `ingest.py` | Capture orchestration, normalization, DuckDB tables/views, and snapshot restore. |
| `ingest_sources.py` / `arcgis.py` | ArcGIS source discovery and verified downloads. |
| `status.py` | Current database coverage and quality-flag summary. |
| `config.py` | Shared normalization dictionaries plus legacy paths/settings. Its `DB_PATH` points to the **legacy** database; current ingest/export paths are defined in their own modules. |
| `test_dashboard.py` / `test_ingest.py` | Export/build and ingest regression tests. |
| `data/act181_ingest.duckdb` | Current research database, including successful captures. |
| `in/snapshots/<timestamp>/` | Saved GeoJSON, metadata, map documents, and manifest for a capture. |
| `out/dashboard/` | Generated static website and JSON exports. Edit the source files, not this directory. |
| `legacy_extract.py`, `legacy_status.py`, `transform.py`, `analyze.py` | Original workflow using `in/*.geojson`, `data/act181.duckdb`, and legacy files in `out/`. |

## Run

Prerequisites: Python **3.9+**, `uv`, and `make`. Run commands from the repository
root. `uv sync` installs the locked Python dependencies into `.venv`; no Node.js,
npm, frontend framework, or ArcGIS credentials are required. First-time dependency
and spatial-extension installation need network access; ordinary website builds
use local data once the environment is set up.

```sh
uv sync
make                              # export existing data + build static dashboard
make serve                        # build, then preview at http://127.0.0.1:8000
make status                       # current RPC/stage coverage and eligibility counts
make test
```

Open `out/dashboard/index.html` directly, or use `make serve`. The HTML includes
its data, styling, and JavaScript. Saved polygons and the table work offline;
the OpenStreetMap street basemap loads online tiles with visible attribution.
The map starts at step 1 of a three-step story: boundaries, designated areas,
then likely exemption eligibility. Previous/next arrows preserve the map extent.
On the last transition, likely ineligible areas turn red, then towns with no
remaining likely eligible areas turn red. Previously excluded towns stay red.
Reduced-motion preferences skip
the animations. RPC boundaries retain their independent toggle.
Step copy and legends live in `steps` in `web/dashboard.js`; ordered `groups`
define the feature selections and style changes between chapters. The
story panel combines navigation, title, description, and the current map key.
It occupies a fixed 22rem column to the right of the map; below 44rem of map
panel width, the map stacks above it. Copy and legend entries wrap naturally,
and the panel grows with its content without an internal scroll area.
Add chapter copy and legend entries to `steps` without changing the HTML layout.
The reusable
`web/story-animation.js` compiles these into a reversible timeline. One timing
configuration controls phase duration (900 ms), gap ratio (0.5), and reverse
speed (2). The first transition has three phases (3.6 seconds forward, 1.8 in
reverse); the second has two (2.25 seconds forward, 1.125 in reverse).
Changing direction mid-phase moves the same playhead back through
the same easing curve without resetting styles or leaving stale timers.
Test the timeline with `node --test test_story_animation.cjs` (Node.js required
only for this animation test, not to build or run the dashboard).
Hover over an interim area for its name, municipality, likely exemption status,
and four reported criteria. Towns and RPC boundaries are noninteractive; there
are no click popups. Hover criteria use the embedded table records matched by
source feature ID, preserving Yes, No, and Unknown.
Use View Vermont to reset the map extent. Scroll-wheel zoom is disabled to keep
page scrolling smooth. No database server is needed. The local preview server
is only serving files.

Keep the preview process running while viewing the page; stop it with Ctrl+C.
After editing source files, rebuild and reload the browser. There is no automatic
watcher or live reload.

### Everyday website work: no ingest required

| Command | What it does |
|---|---|
| `make` / `make build` | Read the existing database, regenerate JSON exports, and build the page. |
| `make export` | Regenerate website datasets only. |
| `uv run python build_dashboard.py` | Rebuild HTML from existing exports after a page/style change; does not query the database. |
| `make serve` | Build locally and serve `out/dashboard` on port 8000. |
| `make clean` | Remove only generated `out/dashboard` files. Keeps databases and downloaded snapshots. |
| `make rebuild` | Clean and rebuild only the dashboard. |
| `make ingest` | **Explicitly download a fresh capture and load it.** Not a dependency of any website target. |

Keep using the existing capture for this project. A missing database causes a
clear build error; it never triggers a download automatically. On another
computer, copy `data/act181_ingest.duckdb`, or restore a saved snapshot with the
command below. A full ingest is necessary only when intentionally obtaining
new source data or when no saved data is available.

### Static dashboard and export contract

The first page presents all 319 interim areas under their source municipality
labels (currently 194 groups), with merged municipality cells. Sort order is
municipality A–Z, then downtown district, village center + buffer, and
town/growth center or development area; names are alphabetical within each type.
Grouping normalizes whitespace/case but does not correct locality names or
assign geographic municipalities. Yes, No, and Unknown have blue, red, and gray
cells. Search and the eligibility/type filters update the groups and counts.

```text
data/act181_ingest.duckdb (read-only)
  → export_data.py
  → out/dashboard/data/manifest.json
  → out/dashboard/data/interim-areas.json
  → out/dashboard/data/map.json
  → build_dashboard.py + web/{index.html,dashboard.css,dashboard.js}
  → out/dashboard/index.html
```

Each dataset export includes `schema_version`, `snapshot_id`, `captured_at`,
`exported_at`, `source_view`, and `source_urls`. `interim-areas.json` adds a
`summary` and ordered `municipalities`, each containing its `municipality` label
and `areas` array. Area records contain source IDs, name, municipality, category,
exemption type, likely eligibility, and the four criteria as true/false/null.
Geometry is intentionally omitted from this table dataset. `map.json` is a
separate compact geometry export containing interim areas, municipality
boundaries, RPC boundaries, and the spatially derived town-level eligibility
summary used by the Leaflet map.

To add a dataset, add an exporter to `EXPORTERS` in `export_data.py`. `make export`
and `make build` automatically include registered exports and update the dataset
manifest. Add a consumer in `web/` / `build_dashboard.py` when a page needs it.
This keeps later website changes independent of ingestion. Rebuild the HTML
after changing data exports, since the standalone page embeds its dataset.

### Initial setup or an intentional data refresh

```sh
make ingest                       # network: discover, download, and load fresh data
# equivalent: uv run python extract.py
```

The DuckDB spatial extension must be installed once for your DuckDB version:
`uv run python -c "import duckdb; duckdb.connect().execute('INSTALL spatial')"`.
It is already installed in this project's current environment.

Each explicit ingest invocation rediscovers the maps and makes a fresh, dated capture. There is
no implicit reuse of the old June cache. A completed capture is written to
`in/snapshots/<UTC timestamp>/`; all successful captures are retained in
`data/act181_ingest.duckdb`. To rebuild from an existing capture without network:

```sh
uv run python extract.py --snapshot in/snapshots/<UTC timestamp>
# Optional: --db /path/to/another.duckdb; --workers 1 through 8 (default 4)
```

Reloading the same snapshot replaces that run transactionally; it does not
duplicate it. Failed downloads or database loads exit unsuccessfully and leave
the previous successful run available. An incomplete download has no manifest.
`make clean` and `make rebuild` only affect the dashboard output; neither deletes
captures/databases nor invokes ingestion.

### Backups and moving to another computer

**`in/`, `data/`, and `out/` are Git-ignored. A Git clone does not include the
research data or the built dashboard.** Back up the current database and the
completed snapshot directories separately. Stop any ingest/restore writer before
copying the database so the copy represents a completed state.

For a new machine, install dependencies with `uv sync`, install the DuckDB spatial
extension for that environment, and either place a database copy at
`data/act181_ingest.duckdb` or copy a complete snapshot and restore it:

```sh
# Replace the example directory with the snapshot you copied.
uv run python extract.py --snapshot in/snapshots/20260908T190421.271250Z
make
```

Restoring the same snapshot is repeatable and uses no ArcGIS downloads. A copied
database may contain old absolute `snapshot_path` references; copying/restoring
the snapshot updates the restored run's path to its new location. Exporting the
database does not require the original snapshot path to exist. Generated website
files can always be rebuilt. To share just the dashboard, copy its standalone
`index.html`, or serve the contents of `out/dashboard/` from a static host.

## Extending and checking the project

For a page-only edit, change `web/`, run `uv run python build_dashboard.py`, and
reload the preview. For a new data field or dataset, change `export_data.py`, add
the corresponding page consumer, and run `make build`. Only modify ingestion
when the saved source data actually lacks the required information. Many extra
fields are already present in `raw_properties`.

Exporter functions receive a read-only DuckDB connection and return a
JSON-serializable object. Register them in `EXPORTERS`; include `title`,
`source_view`, and `source_urls`, and preserve real boolean/null values. The
export runner adds version and capture metadata. For example, the existing
registration is:

```python
EXPORTERS = {'interim-areas': export_interim}
```

Update consumers when an export schema changes, and update the schema version
when the shape is incompatible. The page builder currently accepts interim
schema version 1. Keep geometry exports separate from lightweight table data.

Run `make test` for logic changes. The tests cover ingest completeness and
rollback, grouping/order, missing values, missing-database behavior, and safe
HTML embedding. After changing exports, reconcile row counts and representative
values against the source view. After changing rendering/filtering, check the
page's merged cells, Yes/No/Unknown states, filters/reset, and horizontal scrolling.
Documentation-only changes need link/command checks rather than a new ingest.

### Troubleshooting

| Symptom | Next step |
|---|---|
| Missing database or no successful capture | Copy the saved database or restore a completed snapshot. Do not automatically run an ingest. |
| Missing `spatial` extension/function | Install the extension once for the current DuckDB version; execute `LOAD spatial;` in SQL connections that use spatial functions. |
| Missing export JSON when building the page | Run `make export`, or use `make build` to export and build together. |
| Page still shows old content | Rebuild HTML and reload the browser. Updating JSON alone does not change an already embedded dataset. |
| Port 8000 is occupied | Reuse the existing preview if it serves this dashboard, or use `python3 -m http.server 8001 --bind 127.0.0.1 -d out/dashboard` after building. |
| DuckDB reports a conflicting writer lock | Let the ingest/restore finish and close other write connections before building. |
| Snapshot checksum mismatch or absent manifest | Use an intact completed snapshot; do not edit checksums to accept changed or partial files. |
| Criteria say Unknown or a town name looks unusual | Check `raw_properties` and the source inventory. Missing criteria and source locality labels are preserved intentionally. |

## Sources and scope

The ingest resolves Experience Builder → web map → queryable ArcGIS REST layers:

- [Future Land Use & Tier 1A/B viewer](https://experience.arcgis.com/experience/58543fd6882d4bd6bd0b3008d98e874e/page/Main-Map-Page).
- [Interim Act 250 viewer](https://experience.arcgis.com/experience/d96022b7dce64945a326e7bf98a2f365/).
- [Approved FLU item](https://www.arcgis.com/home/item.html?id=bf09ba3367404b88933b55f31726ab81),
  published by the same state organization but missing from the viewer's
  approved group when inspected September 8, 2026. The item resolves the
  current service URL; this additional source is explicit in `ingest_sources.py`.
- [VT Data - Town Boundaries](https://geodata.vermont.gov/datasets/3f464b0e1980450e9026430a635bff0a),
  the VCGI BNDHASH municipality layer (256 records when verified September 8, 2026).
- [VT Data - RPC Boundaries](https://geodata.vermont.gov/datasets/b311ad21d306477eb2bbefa95fe6460d),
  the matching BNDHASH Regional Planning Commission layer (11 records when verified).

The two boundary sources are resolved from their stable ArcGIS item IDs on each
capture, then downloaded and checked with the same complete-ID, count, geometry,
edit-time, snapshot, and checksum safeguards as the Act 181 sources. BNDHASH is
VCGI's integrated general-mapping boundary dataset; the publisher explicitly
states that it is not a legally definitive boundary source.

Interim layers I–III are included: downtown districts; town/growth centers and
development areas; village centers with their existing buffers. Layers IV–V
(priority housing projects and urbanized transit buffers) are excluded.

FLU and tier sources include both pre-application and application RPC layers,
the approved tier service, and the approved FLU service. All FLU types are kept,
including types outside DC/VC/VA/PGA. Hamlet point layers and the viewer's
under-review Tier 1A source are also retained. Reference layers such as parcels,
water infrastructure, flood zones, and basemaps are outside this ingest.

RPC labels, stage groups, URLs, definition expressions, popups, renderers, and
field metadata are saved. Layer visibility is ignored: a hidden layer can still
contain requested data. Sources are downloaded once per distinct URL, even when
many RPC/stage layers refer to them. The server evaluates each map filter to
record exact feature membership. Empty map layers remain in the catalog with
`feature_count = 0`.

## Database

See the **[table and column reference](DATA_DICTIONARY.md)** for every stored
table's columns, types, meanings, view schemas, current row counts, and examples.

| Table/view | Meaning |
|---|---|
| `ingest_runs` | Capture times, snapshot directory, manifest |
| `ingest_sources` | Source URLs, counts, complete field/domain metadata, per run |
| `ingest_features` | One feature per source URL + object ID + run, all runs |
| `ingest_layers` | Map layer definitions, filters, stages, RPC context and counts, all runs |
| `ingest_memberships` | Features belonging to each map layer, all runs |
| `current_features` | Source features in the latest successful capture |
| `current_layers` | Layer catalog in the latest successful capture |
| `unmapped_features` | Current source records outside all selected map filters |
| `map_features` | Current features with map stage, RPC, and layer membership |

Mapping views expose separate logical layers:

- `interim_areas`, plus `interim_downtown_district`,
  `interim_town_growth_development`, and `interim_village_center_buffer`.
- `tier1b_pre_application`, `tier1b_application`, `tier_approved`.
- `flu_pre_application`, `flu_application`, `flu_approved`.
- `hamlet_features` (points, with `map_stage`).
- `municipal_boundaries` and `rpc_boundaries` (reference polygons, with
  `map_stage = 'reference'`).

`tier_approved` retains **all** approved tier types. Filter `tier_code = '1B'`
when only Tier 1B is wanted. Stage-specific views follow the web map grouping;
`APP` is a submission version and does not imply approval is pending.

Every feature preserves:

- `geom`: native DuckDB `GEOMETRY`, longitude/latitude WGS84 (EPSG:4326).
- `geometry_geojson`: the returned GeoJSON geometry. No requested coordinate
  rounding, simplification, splitting of multipart areas, union, or repair.
- `geometry_valid`: spatial validity flag. Invalid and missing geometries are
  retained and counted instead of silently dropped.
- `raw_properties`: complete original attributes, including dates, notes,
  source IDs, and fields without a normalized column.
- `decoded_properties`: the same attributes with coded-value domain labels.
- Convenient typed columns: RPC, name, municipality, GEOID, FLU/tier code,
  submission version, LURB status/date, interim eligibility and criteria.

`feature_id` combines a URL hash and object ID. It is a source identity, **not**
a guaranteed permanent real-world area ID: publishers can republish services or
renumber records. `source_globalid` is also retained when supplied. Copies in
different services remain distinct, including overlaps between submitted and
approved services. `map_features` may repeat a source feature across different
map layers; use `current_features` for source-level counting.

### Interim eligibility fields

| Structured field | Source field |
|---|---|
| `likely_eligible` | `ExemptionApplied_Y_N_` |
| `zoning_bylaws` | `ZoningAndSubdivisionBylaws` |
| `drinking_water` | `Water`, or `DW_Status` for village buffers |
| `sewer_wastewater` | `Sewer`, or `WW_Status` for village buffers |
| `adequate_soils` | `AdequateSoils` |

`Y`/`Yes` become true; `N`/`No` become false. Missing, blank, and unrecognized
values become NULL, with the original values preserved in `raw_properties`.
`criteria_fields` records which source fields exist, distinguishing an absent
criterion from a present but empty one. The town/growth/development source has
no zoning field. Eligibility is the **publisher's likely-eligibility label**;
the pipeline does not recompute legal eligibility from the criteria.

```sql
LOAD spatial;

SELECT name, municipality, likely_eligible,
       zoning_bylaws, drinking_water, sewer_wastewater, adequate_soils,
       ST_AsGeoJSON(geom) AS geometry
FROM interim_areas;

SELECT rpc, tier_code, lurb_status, date_lurb, ST_AsGeoJSON(geom)
FROM tier_approved;

-- Includes empty RPC/stage layers, which feature-only counts would omit.
SELECT rpc, kind, stage, feature_count
FROM current_layers
WHERE kind IN ('flu', 'tier')
ORDER BY rpc, kind, stage;
```

## Completeness and interpretation

Downloads enumerate object IDs, compare them to server counts, and request
bounded ID batches with all fields and geometry. Truncated batches are split;
missing or duplicate IDs fail the capture. IDs and available service edit
timestamps are checked again for changes. This detects many concurrent edits,
but the public services do not offer an atomic statewide historical snapshot.
The manifest stores capture times and SHA-256 checksums of every source file.

The current application service can contain already approved records, and
published geometry may have been edited in place. Downloading it today cannot
recover the geometry exactly as originally submitted. Dated captures support
future comparisons; historical comparisons require historical source versions.
No cross-stage intersections or change metrics are computed here.

The [September 8 source inventory](SOURCE_INVENTORY.md) records the first
completed ingest's counts, published coverage, and geometry flags.

The original analysis remains documented in [LEGACY_ANALYSIS.md](LEGACY_ANALYSIS.md).
`make legacy` runs it against the original cache and `data/act181.duckdb`;
it does not use this new ingest database. The prior extractor is
`legacy_extract.py`. The current dashboard uses the new ingest database.
