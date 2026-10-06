# Research reference

This document holds data contracts, dated source findings, and approved research
decisions. See [README](../README.md) for setup, commands, and editing the dashboard.
Counts below are dated observations, not expectations for future captures.

- [Source scope](#source-scope)
- [Database schema](#database-schema)
- [Dated source findings](#dated-source-findings)
- [Municipality decisions](#municipality-decisions)
- [Dashboard export contract](#dashboard-export-contract)

## Source scope

`extract.py` resolves the [FLU/tier viewer](https://experience.arcgis.com/experience/58543fd6882d4bd6bd0b3008d98e874e/page/Main-Map-Page)
and [interim viewer](https://experience.arcgis.com/experience/d96022b7dce64945a326e7bf98a2f365/)
through their web maps to queryable ArcGIS REST layers. Additional explicit items
are [approved FLU](https://www.arcgis.com/home/item.html?id=bf09ba3367404b88933b55f31726ab81),
[municipal boundaries](https://geodata.vermont.gov/datasets/3f464b0e1980450e9026430a635bff0a),
and [RPC boundaries](https://geodata.vermont.gov/datasets/b311ad21d306477eb2bbefa95fe6460d).
VCGI's BNDHASH boundaries support general mapping; they are not legally definitive.

Interim layers I–III include downtown districts, town/growth/development areas,
and village centers with existing buffers. Layers IV–V (priority housing projects
and urbanized transit buffers) are excluded. All published FLU types, submitted
and approved tier types, hamlet points, and the viewer's under-review Tier 1A
source are retained. Parcels, infrastructure layers, flood zones, and basemaps
are outside the research ingest.

Each distinct source URL is captured once; server-evaluated filters record its
logical map memberships. Hidden and empty selected layers are retained. Raw
metadata, map documents, returned geometry, complete attributes, and SHA-256
checksums remain in each completed snapshot. Missing/duplicate IDs, truncated
responses, count discrepancies, and observed source edits fail capture. These
checks do not provide an atomic statewide historical snapshot. In-place publisher
edits mean a current capture cannot reconstruct original submission geometry.

## Database schema

This describes **`data/act181_ingest.duckdb`**, the current ingest database.
Schema and counts were checked against the database on September 8, 2026,
for snapshot `20260908T222348.634248Z`.

There are **5 stored tables and 18 views**. A view is a saved query that you
can use like a table; it does not store another copy of the data. Shared view
columns are documented once below rather than repeated for every dataset.

### Where to start

| If you want… | Start with |
|---|---|
| Interim areas, eligibility, and criteria | `interim_areas` |
| Proposed and approved Tier 1B geometry | `tier1b_pre_application`, `tier1b_application`, `tier_approved` |
| Future land use geometry and classification | `flu_pre_application`, `flu_application`, `flu_approved` |
| Municipality and RPC reference polygons | `municipal_boundaries`, `rpc_boundaries` |
| Every downloaded feature, including records outside the map filters | `current_features` |
| Available RPC/stage layers, including empty layers | `current_layers` |
| Original source attributes not given their own column | `raw_properties` on any feature table/view |
| Earlier captures | The `ingest_*` tables, filtered by `run_id` |

**Reading the types:** `VARCHAR` is text; `BIGINT` is an integer; `BOOLEAN`
is true/false; `JSON` stores an object or array; `GEOMETRY` is spatial data;
`TIMESTAMP WITH TIME ZONE` is a timestamp with timezone support.
`NULL` means missing, unknown, or not applicable—not false or zero.

### `ingest_features`

**The actual areas and points, with geometry and attributes.** One row per
source feature per capture. Currently **18,377 rows**, with **31 columns**.
The primary key is **(`run_id`, `feature_id`)**; only these two columns are
declared NOT NULL. Other fields may be absent or irrelevant to a particular source.

| Column | Type | Meaning / examples |
|---|---|---|
| `run_id` | VARCHAR | Capture identifier, such as `20260908T190421.271250Z`. Links to `ingest_runs`. |
| `feature_id` | VARCHAR | Source URL hash plus source object ID, separated by `:`. Unique within a capture, not a guaranteed permanent real-world area identifier. |
| `source_id` | VARCHAR | 16-character hash identifying the ArcGIS layer URL. Links to `ingest_sources` within the same run. |
| `source_oid` | VARCHAR | Original ArcGIS object ID (`OBJECTID` or `FID`), stored as text. |
| `source_globalid` | VARCHAR | Publisher's `GlobalID`, when available; useful for investigating identity across service copies or updates. |
| `kind` | VARCHAR | Dataset family: `interim`, `flu`, `tier`, `hamlet`, `municipality_boundary`, or `rpc_boundary`. |
| `category` | VARCHAR | For interim areas: `downtown_district`, `town_growth_development`, or `village_center_buffer`. Otherwise the dataset family value. |
| `rpc` | VARCHAR | Normalized RPC identifier, usually a two-letter code such as `CC` or `NW`. Uses source attributes, with an unambiguous source-layer RPC fallback. Some missing/nonstandard values remain. |
| `name` | VARCHAR | Display name drawn from designation, community, area, town, or municipality fields. Example: `Alburgh Village Center`. Not guaranteed populated or unique. |
| `municipality` | VARCHAR | Source municipality text from `TOWNNAMEMC`, `TOWNNAME`, `TOWN_NAME`, or `MUNI`. No spatial assignment is performed; most current records leave this NULL. |
| `geoid` | VARCHAR | Source `GEOID` or boundary `TOWNGEOID`, preserved as text so leading zeros are retained. Most current records leave this NULL. |
| `flu_code` | VARCHAR | Normalized future land use code, e.g. `DC`, `VC`, `PGA`, `VA`, `RAF`. Can also be present on tier sources that retain FLU attributes. |
| `tier_code` | VARCHAR | Source tier classification, normally `1B` or `1A`. Missing codes on dedicated Tier 1B sources are filled from layer context; unexpected source codes are retained. |
| `submission_version` | VARCHAR | Normalized submission version, usually `PRE` or `APP`; `AMD` means amendment when supplied. Missing and nonstandard source values remain. **This is not approval status.** |
| `lurb_status` | VARCHAR | Land Use Review Board status from `LURBSTATUS`. Currently `APR` (approved), `RCV` (received), or NULL. |
| `date_lurb` | VARCHAR | Source LURB action date. Current populated values are date strings such as `2026-06-12`; this column is text, not a SQL DATE. |
| `exemption_type` | VARCHAR | Interim area type from `ExemptionArea`, e.g. `Village Center + 1/4 mile buffer`. |
| `exemption_description` | VARCHAR | Source explanation of interim exemption parameters or applicability, from `ExemptionAreaDescription`. |
| `eligibility_raw` | VARCHAR | Trimmed source eligibility flag, currently `Y` or `N`, from `ExemptionApplied_Y_N_`. The untouched value also remains in `raw_properties`. |
| `eligibility_label` | VARCHAR | `Area likely Exemption Eligible` or `Area likely NOT Exemption Eligible`; NULL when the flag is unrecognized or absent. |
| `likely_eligible` | BOOLEAN | Structured version of the publisher's eligibility flag. No legal eligibility calculation is performed. |
| `zoning_bylaws` | BOOLEAN | Interim zoning/bylaws criterion from `ZoningAndSubdivisionBylaws`. The town/growth/development source has no such field. |
| `drinking_water` | BOOLEAN | Interim drinking-water criterion from `Water`, or `DW_Status` for village buffers. Forty village buffers currently have no value. |
| `sewer_wastewater` | BOOLEAN | Interim sewer/wastewater criterion from `Sewer`, or `WW_Status` for village buffers. |
| `adequate_soils` | BOOLEAN | Interim adequate-soils criterion from `AdequateSoils`. |
| `criteria_fields` | JSON | Maps the four normalized criterion names to their source field names. A NULL mapping means the field is absent; `{}` for non-interim features. |
| `raw_properties` | JSON | **All original returned attributes**, including notes, dates, source fields, and values without a dedicated normalized column. Field names and values retain their source form. |
| `decoded_properties` | JSON | Copy of the attributes with available ArcGIS coded-value domain labels substituted, e.g. `APR` → `Approved`. Other values stay unchanged. |
| `geometry_geojson` | JSON | Original returned GeoJSON geometry in WGS84 longitude/latitude (EPSG:4326). Polygon, MultiPolygon, or point geometry as supplied; no requested rounding or repair. |
| `geom` | GEOMETRY | The same geometry converted to DuckDB's native spatial type, also EPSG:4326 coordinates. Use for spatial queries or `ST_AsGeoJSON(geom)` for export. |
| `geometry_valid` | BOOLEAN | Result of DuckDB's spatial validity check. False geometries are retained; NULL when geometry is missing. |

The criteria columns map `Y`/`Yes` to true and `N`/`No` to false. Blank,
missing, and unrecognized values become NULL. They describe source-reported
criteria, not independently verified infrastructure availability.

Source-specific notes, dates, designation links, measurements, and edit history
remain in `raw_properties`; consult `ingest_sources.metadata` for field aliases,
types, domains, and units. These keys vary by service and are not extra SQL columns.

### `ingest_layers`

**The map's logical layers and the filters that define them.** One row per
layer per capture. Currently **62 rows**. Primary key: **(`run_id`, `layer_id`)**.

| Column | Type | Meaning / examples |
|---|---|---|
| `run_id` | VARCHAR | Capture identifier; part of the primary key. |
| `layer_id` | VARCHAR | Web map/item identifier plus layer identifier; part of the primary key. |
| `source_id` | VARCHAR | Identifies the source service layer. Several logical layers can use the same source. |
| `kind` | VARCHAR | `interim`, `flu`, `tier`, `hamlet`, `municipality_boundary`, or `rpc_boundary`. |
| `category` | VARCHAR | Dataset category; same vocabulary as `ingest_features.category`. |
| `stage` | VARCHAR | Map grouping: `pre_application`, `application`, `approved`, `interim`, `under_review`, or `reference`. |
| `rpc` | VARCHAR | RPC from the map's group hierarchy. NULL for statewide or non-RPC-specific layers. |
| `path` | JSON | Array of map group/layer titles, e.g. `["Under Review: FLU & TIER Data", "Addison County RPC", "Application", "FLU Areas"]`. |
| `definition_expression` | VARCHAR | ArcGIS filter defining membership, e.g. `RPC = 'AC' AND TIER_VERS = 'APP'`; `1=1` means no additional map filter. |
| `definition` | JSON | Original map-layer configuration, including renderer/popup settings when present. For the additional approved FLU source, its published service-layer entry. |
| `feature_count` | BIGINT | Number of source features matching this logical layer's filter. Zero-count layers are retained. |

### `ingest_sources`

**Where the data came from and how the publisher defines its fields.** One
row per distinct ArcGIS layer URL per capture. Currently **27 rows**.
Primary key: **(`run_id`, `source_id`)**.

| Column | Type | Meaning / examples |
|---|---|---|
| `run_id` | VARCHAR | Capture identifier; part of the primary key. |
| `source_id` | VARCHAR | Hash of the source layer URL; part of the primary key. |
| `url` | VARCHAR | Queryable ArcGIS REST layer URL ending in `/FeatureServer/<id>` or `/MapServer/<id>`. |
| `expected_count` | BIGINT | Complete source feature count, verified against object IDs and downloaded records. Not restricted to the viewer's map filters. |
| `metadata` | JSON | Complete ArcGIS layer metadata: name, geometry type, field definitions/aliases/domains, object-ID field, query capabilities, and available edit information. |

### `ingest_memberships`

**The link between features and logical map layers.** One row for each
feature's membership in a layer, per capture. Currently **15,978 rows**.
All three columns form the primary key and are NOT NULL.

| Column | Type | Meaning / examples |
|---|---|---|
| `run_id` | VARCHAR | Capture in which this membership was observed. |
| `layer_id` | VARCHAR | Logical layer; links to `ingest_layers` within the same run. |
| `feature_id` | VARCHAR | Source feature; links to `ingest_features` within the same run. |

A feature can belong to multiple layers or none. Memberships come from the
server's evaluation of the map filters, not from a spatial intersection.

### `ingest_runs`

**Capture history and reproducibility information.** One row per successfully
loaded capture. Currently **1 row**. Primary key: **`run_id`**.

| Column | Type | Meaning / examples |
|---|---|---|
| `run_id` | VARCHAR | Unique UTC capture identifier. |
| `started_at` | TIMESTAMP WITH TIME ZONE | When source discovery/download began. |
| `completed_at` | TIMESTAMP WITH TIME ZONE | When capture finished, before database loading; not a source publication date. |
| `snapshot_path` | VARCHAR | Absolute path to the saved snapshot directory. |
| `manifest` | JSON | Capture manifest: schema version, timestamps, CRS, source/layer inventory, membership IDs, and file checksums. |

### Views: current data and map-ready records

The following views select the latest successful run. They have the complete
column sets indicated below, with the same types and meanings as their source
tables. They add no columns unless explicitly listed.

| View | Current rows | Columns | What it selects |
|---|---:|---|---|
| `latest_ingest_run` | 1 | All 5 from [`ingest_runs`](#ingest_runs) | Most recent successful capture by `started_at`. |
| `current_features` | 18,377 | All 31 from [`ingest_features`](#ingest_features) | Every source feature in that capture. |
| `current_layers` | 62 | All 11 from [`ingest_layers`](#ingest_layers) | Every selected logical layer, including empty ones. |
| `unmapped_features` | 2,401 | All 31 from [`ingest_features`](#ingest_features) | Source features with no selected layer membership. |
| `map_features` | 15,978 | All 31 feature columns **plus the 4 below** | Source features joined to their logical map layers. |

### Additional columns in `map_features`

| Column | Type | Meaning / examples |
|---|---|---|
| `layer_id` | VARCHAR | The logical map layer this row belongs to. |
| `map_stage` | VARCHAR | Layer's stage: `pre_application`, `application`, `approved`, `interim`, `under_review`, or `reference`. Independent of `submission_version` and `lurb_status`. |
| `map_rpc` | VARCHAR | RPC from the layer's map hierarchy. Unlike feature `rpc`, this can be NULL for an approved statewide layer even when the feature has a known RPC. |
| `map_path` | JSON | Array of map group/layer titles identifying the feature's placement in the viewer. |

One source feature can appear more than once in `map_features`, once per
layer membership. Identify a row by **(`run_id`, `layer_id`, `feature_id`)**.

### Views: individual datasets

**Each of these views has all 35 columns from `map_features`**: the 31-column
feature table above plus `layer_id`, `map_stage`, `map_rpc`, and `map_path`.
Only the row filter changes. No aggregation, geometry repair, or merging is
performed by these views.

| View | Current rows | Description / filter |
|---|---:|---|
| `interim_areas` | 319 | All three interim categories; `kind = 'interim'`. |
| `interim_downtown_district` | 25 | Downtown District Area; `category = 'downtown_district'`. |
| `interim_town_growth_development` | 40 | Town/growth centers and development areas; `category = 'town_growth_development'`. |
| `interim_village_center_buffer` | 254 | Village centers with their existing buffers; `category = 'village_center_buffer'`. |
| `tier1b_pre_application` | 407 | `kind = 'tier'`, `tier_code = '1B'`, `map_stage = 'pre_application'`. |
| `tier1b_application` | 77 | `kind = 'tier'`, `tier_code = '1B'`, `map_stage = 'application'`. |
| `tier_approved` | 59 | `kind = 'tier'`, `map_stage = 'approved'`. All tier types retained; currently all are `1B`. |
| `flu_pre_application` | 10,315 | All FLU types in pre-application layers; `kind = 'flu'`, `map_stage = 'pre_application'`. |
| `flu_application` | 2,236 | All FLU types in application layers; `kind = 'flu'`, `map_stage = 'application'`. |
| `flu_approved` | 2,200 | Approved FLU service; `kind = 'flu'`, `map_stage = 'approved'`. |
| `hamlet_features` | 92 | Hamlet point layer memberships; `kind = 'hamlet'`. Includes 90 source records, with two appearing in both stage groups. |

A capture made with the boundary-enabled pipeline also creates
`municipal_boundaries` (`kind = 'municipality_boundary'`) and `rpc_boundaries`
(`kind = 'rpc_boundary'`). Both retain all publisher attributes and unmodified
source geometry. The current capture contains 256 municipality polygons and 11
RPC polygons.

The website's `map.json` (schema version 2) keeps geometry separate from the
table export. It consumes prepared municipality relationships derived from
normalized source labels plus the approved crosswalk, not intersections.
`has_designated_area` means at least one assigned area; `has_likely_eligible`
means at least one assigned area with publisher status true. Unknown status
remains null on each area and does not qualify as true. These flags are a display
summary, not a legal determination or whole-town exemption.

The export includes `membership_version` (currently 1), `membership_basis`, and
`memberships`: one object per `(feature_id, municipality_geoid)` containing those
keys plus `source_municipality`, official `municipality`, and `method`
(`normalized_exact`, `approved_alias`, or `approved_feature_override`).
Original labels and geometry are preserved. Missing/invalid geometry does not
prevent membership. Unmatched labels or missing/ambiguous target GEOIDs fail
preparation for review, with no spatial fallback.

The approved September 12, 2026 derivation yields 319 areas, 320 memberships
(Jericho–Underhill has two), 187 municipalities with areas, 118 with a likely
eligible area, 69 with areas but none likely eligible, and 69 without areas.
Rutland City overrides are limited to the three reviewed source features;
Tyson maps to Plymouth. The table still groups 194 original source labels.
See [municipality decisions](#municipality-decisions) below.

### Prepared municipality relationships

`data/municipality-memberships.json` is a derived sidecar, not a new database
table. `make prepare` (also a dependency of build/export/analyze) reads the saved
database and writes it without reloading source data. Snapshot transformation
also prepares it. It can be regenerated; raw snapshots and DuckDB are unchanged
by preparation.

Build incrementality, October 6, 2026: GNU Make tracks the saved database,
preparation/export code, configuration, and dependency files by modification
time. Sidecars and exports are grouped file targets; unchanged builds skip
their recipes. When preparation is required, Make forces spatial recomputation
and touches all successfully prepared sidecars, including unchanged membership
content, so newer prerequisites do not cause repeated preparation. Existing
provenance checks and export publication remain in place. `make page` consumes
existing exports only; `make -B build` forces the complete offline build.

The current file schema is version 1:

| Field | Meaning |
|---|---|
| `schema_version` | Prepared file contract version (1). |
| `snapshot_id` | Successful source capture used for this derivation. |
| `membership_version` | Approved crosswalk version (1). |
| `membership_basis` | Recorded municipality with approved crosswalk; no spatial fallback. |
| `rules_sha256` | SHA-256 of the approved alias values, feature exceptions, and membership version (comments and formatting do not affect it). |
| `inputs_sha256` | SHA-256 of ordered source area IDs/labels/categories and boundary labels/GEOIDs. |
| `memberships` | The relationship objects documented above, one per area and municipality GEOID. |

Export validates these provenance fields against its read-only database
transaction and current rules. Missing/stale preparation stops export with an
instruction to run `make prepare`. No public table/map export schema changed.

The UI groups water, wastewater, and soils as infrastructure alternatives. Its
display-only summary is true if any value is true, false if all are false, and
null otherwise. It does not replace `likely_eligible`. For the
`town_growth_development` category, the table displays “Not separately required”
for zoning and the hover omits zoning; the exported source null is unchanged.

### Relationships and interpretation

Always include `run_id` when joining the stored tables: IDs can repeat across
captures. Relationships are implemented through these shared columns; the
database does not declare foreign-key constraints.

| From | Join to | Join columns |
|---|---|---|
| Any `ingest_*` table | `ingest_runs` | `run_id` |
| `ingest_features` or `ingest_layers` | `ingest_sources` | `run_id`, `source_id` |
| `ingest_memberships` | `ingest_features` | `run_id`, `feature_id` |
| `ingest_memberships` | `ingest_layers` | `run_id`, `layer_id` |

An application record can already be approved: `submission_version = 'APP'`
and `lurb_status = 'APR'` can coexist. Stage views are not mutually exclusive.
Counts across views or services should not be added as unique real-world areas.

The current capture has **14 missing geometries** and **908 invalid geometries**,
all retained. The **2,401 unmapped records** also remain available; some are
alternate source copies, while others have missing/nonstandard classifications.
See [dated source findings](#dated-source-findings) below.

## Dated source findings

### September 8, 2026

Capture `20260908T190421.271250Z` contains **18,110 source features**, downloaded
from **25 distinct ArcGIS layer URLs**, with **60 logical map layers**. These
are source-feature counts, not municipalities, connected polygons, or unique
real-world areas. A source feature can be a multipart geometry. Different
services can contain copies of the same area.

The full source URLs, map configuration, filters, and field domains are stored
in the snapshot manifest and in `ingest_sources` / `ingest_layers`. Local data:
`data/act181_ingest.duckdb`, with raw files in
`in/snapshots/20260908T190421.271250Z/`.

This is a historical inventory of the first capture. The current
boundary-enabled capture is `20260908T222348.634248Z` and adds VCGI's BNDHASH
town and RPC items (256 and 11 polygons, respectively). The historical counts
above remain unchanged so dated source findings stay reproducible.

### Interim exemption areas

The [interim web map](https://www.arcgis.com/home/item.html?id=e1b2aaa4aac344cea6d249737abaa45f)
uses these queryable layers of the state ANR service:

| Layer | Records | Likely eligible | Likely not eligible |
|---|---:|---:|---:|
| [Downtown District Area — 6](https://anrmaps.vermont.gov/arcgis/rest/services/map_services/MAP_ACCD_DHCD_WM_NOCACHE/MapServer/6) | 25 | 24 | 1 |
| [Town and Growth Centers & Development Areas — 7](https://anrmaps.vermont.gov/arcgis/rest/services/map_services/MAP_ACCD_DHCD_WM_NOCACHE/MapServer/7) | 40 | 40 | 0 |
| [Village Center & Buffer — 11](https://anrmaps.vermont.gov/arcgis/rest/services/map_services/MAP_ACCD_DHCD_WM_NOCACHE/MapServer/11) | 254 | 150 | 104 |
| Total | 319 | 214 | 105 |

Eligibility comes from `ExemptionApplied_Y_N_`, also used by the viewer's
renderer and popup. The town/growth/development layer lacks a zoning/bylaws
field. Forty village buffers have NULL drinking-water status. These values
remain NULL in the structured data. No eligibility rules are inferred.

### FLU and Tier 1B stage views

The [FLU web map](https://www.arcgis.com/home/item.html?id=509abf408c8a4e31964edefd997c1e84)
combines statewide services with individual RPC sources. Published map
membership yields the following counts, including records without geometry:

| RPC | FLU pre-app | FLU app | FLU approved | Tier 1B pre-app | Tier 1B app | Tier approved |
|---|---:|---:|---:|---:|---:|---:|
| AC | 64 | 0 | 0 | 50 | 0 | 0 |
| BC | 318 | 0 | 0 | 7 | 0 | 0 |
| CC | 148 | 168 | 168 | 36 | 41 | 41 |
| CV | 4,799 | 0 | 0 | 50 | 0 | 0 |
| LC | 11 | 11 | 0 | 7 | 4 | 0 |
| MA | 25 | 25 | 0 | 15 | 14 | 0 |
| NV | 1,289 | 0 | 0 | 67 | 0 | 0 |
| NW | 1,913 | 1,971 | 1,971 | 56 | 1 | 1 |
| RR | 304 | 61 | 61 | 31 | 17 | 17 |
| TR | 794 | 0 | 0 | 44 | 0 | 0 |
| WR | 650 | 0 | 0 | 44 | 0 | 0 |
| Total | 10,315 | 2,236 | 2,200 | 407 | 77 | 59 |

Zero means no features returned for that layer/filter at capture time. It does
not establish that a region has not submitted an application elsewhere.
All 59 approved tier records currently have `TIER_AREA = '1B'`.

Approved data comes from separate public services:

- [Approved tier areas](https://services1.arcgis.com/rnCtPMpypTkqwvYT/arcgis/rest/services/LURB_ApprovedTierMap_Poly_SP_Public/FeatureServer/0).
- [Approved FLU areas](https://services1.arcgis.com/rnCtPMpypTkqwvYT/arcgis/rest/services/LURB_ApprovedFLUAreas_Poly_SP_Public/FeatureServer/1),
  discovered through the state publisher's ArcGIS catalog. This service was
  absent from the viewer's approved group.

Approved records retain `APP` submission versions and have `APR` LURB status.
The application layers include approved records; these stages are not
mutually exclusive. Matching counts do not prove unchanged geometry between
submission and approval. Earlier submission geometry may have been edited in
place and cannot be reconstructed from this capture alone.

The capture also preserves 90 source hamlet points (92 map memberships because
the Lamoille point source appears under both stages) and 6 records from the
under-review Tier 1A source.

### Retained source irregularities

- **14 records lack returned geometry**, including four approved FLU records
  also present in the statewide FLU service. A native ArcGIS JSON query for
  approved FLU object 19439 also returned no geometry, confirming this example
  is absent at the source rather than lost in GeoJSON conversion.
- **908 records fail DuckDB spatial validity checks.** They retain their
  returned geometry with `geometry_valid = false`. Geometry repair, if needed
  for later intersections, should create a derived geometry with an audit trail.
- **2,401 source records do not match any selected map-layer filter**:
  1,916 FLU and 485 tier records. These remain in `unmapped_features`. Examples
  include the statewide NW pre-application FLU copy (the viewer uses an RPC
  source instead), missing RPC/version fields, and non-Tier-1B records excluded
  by the Chittenden application filter. No old Windham repair heuristic is applied.

These counts include copies across services, so they are not counts of distinct
real-world defects. All 18,110 downloaded records were loaded; flagged and
unmapped records were not discarded.

## Municipality decisions

Approved September 12, 2026 against the saved capture. `transform.py` normalizes
case/whitespace and applies the exceptions in `config.py`; geographic overlap
never supplies a fallback. Unknown labels and ambiguous/missing target GEOIDs
stop preparation. Source labels and geometries are preserved. The table groups
by source labels; map summaries count official municipality GEOIDs.

| Source label (case-insensitive) | Approved municipality membership | Records | Basis / scope |
|---|---|---:|---|
| ALGIERS | Guilford | 1 | Locality; saved polygon lies in Guilford. |
| ENOSBURG | Enosburgh | 1 | Spelling; Enosburg Falls polygon lies in Enosburgh. |
| ESSEX TOWN | Essex | 1 | Town suffix; do not merge Essex Junction. |
| FERRISBURG | Ferrisburgh | 1 | Spelling variant. |
| GREENSBORRO | Greensboro | 2 | Misspelling; both named Greensboro centers. Greensboro Bend also extends into three neighbors; those intersections do not create membership. |
| JERICHO\UNDERHILL | Jericho + Underhill | 1 | Explicit shared label and user confirmation: one area, two memberships. |
| MIDDLETOWN | Middletown Springs | 1 | Full town name; area name is Middletown Springs Village Center. |
| N HERO | North Hero | 1 | Abbreviation. |
| Rutland | Rutland City | 3 | Feature-specific rule for the three current NDA records (IDs 21, 22, 23), all wholly within Rutland City. Do not assume every future “Rutland” label means the city. |
| S SHAFTSBURY | Shaftsbury | 1 | South Shaftsbury locality. |
| ST. ALBANS CITY / St. Albans City | Saint Albans City | 2 | Saint expansion; preserve city/town distinction. |
| ST. ALBANS TOWN | Saint Albans Town | 1 | Saint expansion; preserve city/town distinction. |
| ST. JOHNSBURY / St. Johnsbury | Saint Johnsbury | 2 | Saint expansion. |
| TYSON | Plymouth | 1 | Plymouth is the approved designation owner; the buffer also crosses Ludlow. |
| VILLAGE OF MANCHESTER | Manchester | 1 | Village is represented within Manchester by this municipal-boundary dataset. |
| West Brattleboro | Brattleboro | 1 | Locality; current NDA is wholly in Brattleboro. |

Riverside/Underhill Flats (`a8a69a8957ab82c6:50`) belongs to both Jericho and
Underhill: two relationships referencing one unchanged source feature. This
accounts for 320 relationships across 319 source areas.

Tyson is assigned to Plymouth as the designation owner. Its buffered geometry
crosses Ludlow; this assignment does not claim the whole buffer lies in Plymouth.
Plymouth's site and zoning ordinance identify Tyson as its designated center;
Ludlow's plan describes the hamlet as straddling the town line. The approved
choice was Plymouth-only membership. Adding Ludlow would not change the town
totals in this capture because Ludlow already has another likely eligible area.

Sources: [Plymouth official site](https://plymouthvt.org/wordpress/), [Plymouth zoning ordinance](https://plymouthvt.org/wordpress/wp-content/uploads/2023/03/PLYMOUTH-ZONING-ORDINANCE-ADOPTED-5-21-2024.pdf), [Ludlow plan](https://www.ludlow.vt.us/vertical/sites/%7B78E8DA21-0D46-4486-AF59-9D2B5A1048F3%7D/uploads/Planning_Commission_March_Agenda__Supporting_Documents1.pdf). The source references `VDtyson.pdf`; that original designation map was not retrieved during this review.

### Recorded September 12 comparison

All 319 areas had source labels: 298 matched by case/whitespace normalization,
and 21 required the 16 exception rules above. Intersections were used only as
an audit diagnostic. The recorded comparison with the prior spatial method was:

| Municipality summary | Prior intersection method | Approved membership |
|---|---:|---:|
| With designated areas | 195 | 187 |
| With a likely eligible area | 126 | 118 |
| With areas, none likely eligible | 69 | 69 |
| No designated areas | 61 | 69 |

| Municipality | Prior intersection method | Approved membership |
|---|---|---|
| Dummerston | Likely eligible area | No designated areas |
| Fayston | Likely eligible area | No designated areas |
| Jamaica | Likely eligible area | Areas, none likely eligible |
| Johnson | Likely eligible area | Areas, none likely eligible |
| Leicester | Likely eligible area | No designated areas |
| Mount Holly | Likely eligible area | Areas, none likely eligible |
| Mount Tabor | Areas, none likely eligible | No designated areas |
| Ryegate | Likely eligible area | Areas, none likely eligible |
| Sheffield | Areas, none likely eligible | No designated areas |
| Stannard | Areas, none likely eligible | No designated areas |
| Sutton | Likely eligible area | No designated areas |
| Walden | Areas, none likely eligible | No designated areas |

The exhaustive unchanged-name mapping is available in the exported `memberships`
array; it is not duplicated here.

## Dashboard export contract

RPC focus counts use the saved RPC containing each municipality's interior
point (`ST_PointOnSurface`), exported as `focus_rpc`. This display-only reference
assignment leaves approved interim-area memberships and eligibility flags intact;
border slivers do not confer membership in a second RPC. The September 8 snapshot
assigns all 256 towns uniquely across 11 RPCs. Focus selection recomputes all five
chapters' counts. Overlay visibility follows municipality RPC membership, using
the existing approved memberships for interim areas (shared areas remain visible
if either municipality belongs to the focus). Selected features retain their
full geometry, including border spillovers. Other overlays fade out independently
of story styling; basemap tiles remain visible everywhere.

The preserved `act181` story (currently disabled) uses the following chapter
sequence. The active four-chapter housing growth story introduces qualifying
future land use, highlights municipalities with included growth areas, compares
growth blocks with mapped Tier 1B, and summarizes municipal coverage.
Its independent schema-1 export leaves the existing map/table contracts
unchanged; the methodology is documented below.

The original fourth chapter overlays the working Tier 1B map in teal (#287f89),
with 60% fill opacity. Hover labels identify the selected stage and RPC.
Its transition cools old negative municipal colors to brown while replacing
interim polygons with Tier 1B wherever the municipality has a working Tier 1B area.
Elsewhere, nonexempt interim polygons disappear and exempt polygons remain brown.
It then highlights municipalities with Tier 1B but no temporary exemption in green.
The fifth chapter cools those gains to teal, then highlights the remaining
temporary-only exempt polygons and their municipalities in coral.
Municipalities with both stay teal; those with neither stay brown. Comparison uses
official GEOIDs from the existing memberships and selected municipal Tier 1B
export, not new spatial intersections or all historical Tier 1B stages.
Step two introduces designated areas in teal and their municipalities in gain green,
and municipalities without areas in coral. At the beginning of the transition
to step three, those colors settle to teal and brown before new ineligible
areas and municipalities turn coral. Step four settles prior losses to brown
while introducing Tier 1B polygons in teal and then new municipal gains in green.
Green is reserved for municipal delta highlights. Story keys use “temporary
exemptions” and “Exempt” / “Not exempt”; source eligibility fields are unchanged.
Hidden interim polygons do not receive pointer events;
reverse navigation restores their previous styles and interactions.

`tier1b.json` (schema 3) exports the prepared municipal working map separately from
the existing map/table contracts, with capture/export provenance and source URLs.
Each feature identifies its municipality/GEOID, RPC and stage, with source indices
linking to source feature/object/layer IDs and publisher submission/approval fields.
Geometry is derived using the rules below. The page validates its generation against the other
exports. Source acquisition is not needed.

Approved September 14, 2026: `tier1b_working` selects the furthest populated
Tier 1B map stage for each feature RPC: approved > application > pre-application.
An empty stage means that region has not completed that stage. Selection is
region-wide, not per municipality or individual polygon, and uses `map_stage`,
not `submission_version` or `lurb_status`. All rows in the selected stage remain,
including missing/invalid geometry; no spatial repair or deduplication is implied.
Original stage views and source records remain available. The view preserves all
`map_features` columns, including stage and provenance, without storing copies.
This rule describes the saved capture, not live application progress.

### Municipal Tier 1B derivation — approved September 14, 2026

Display simplification investigation (September 14, 2026): the current
100-record working export has 503 parts and 105 holes.
Independent part simplification with a 5% symmetric-difference safeguard and
two-way boundary-buffer checks reduces the 13.44 MB export to 3.84 MB at 0.5 m,
but changes existing intermunicipal overlaps. Preserving original parts within
twice the tolerance of another municipality's parts avoids those overlap changes
in this snapshot and produces 5.29 MB (1.87 MB gzip). The corresponding 0.25 m
and 0.75 m exports are 6.13 MB and 5.19 MB. These are display-only candidates;
analytical geometry and area metadata remain unchanged. Reproducible experiment
and evidence are saved locally in `out/geometry-review/parts.py`,
`part-simplification.ipynb`, `part-results.json`, and `part-report.html`.
The rules use geometry checks rather than municipality-specific exceptions.
Production integration now includes operation-error fallback and final
serialized-output validation, as described below. The neighbor-protection
experiment preserved existing overlaps rather than repairing them; that
protection was not adopted. Numerical checks do not certify the meaning of
every narrow road or corridor.

Approved and implemented display rule (September 14, 2026): `analyze.py` applies
0.5 m simplification per connected part, retaining originals if symmetric
difference exceeds 5%, holes change, validity fails, or either boundary exceeds
the other's 0.501 m buffer (64 segments per quadrant). Operation errors retain
original geometry. Recombined serialized geometry must remain valid and retain
part/hole counts; otherwise the whole feature falls back. No neighboring-boundary
protection is applied: small display seams/overlap changes are an accepted tradeoff.
`tier1b.json` retains schema 3 and adds `display_simplification` rules, engine
version, and fallback provenance (zero-based part indices). Detailed sidecar
geometry and all area/status/membership properties remain authoritative and
unchanged. Current export: 3.84 MB, 23 part fallbacks, no whole-feature fallbacks.

Display coordinate grid (October 6, 2026): coordinates had 12–15 decimals and
made up about 22 MB of the 26 MB of JSON. After simplification, every exported
feature collection (`map.json`, `tier1b.json`, `housing-growth.json`) is snapped
to a 0.00001° grid (about 0.8 × 1.1 m) with `ST_ReducePrecision`. GEOS
snap-rounding always returns valid geometry. Necks, holes, and parts narrower
than about one grid cell collapse instead of crossing. Two guards, measured in
EPSG:32145, fail the export if any snapped vertex lies more than 1 m from the
original outline, or if any added or removed piece survives a 1 m inward buffer
(that is, is 2 m or wider). Exports keep their schema versions and add
`display_precision` rules, engine, and `changes`: part/hole counts before and
after, or `collapsed_area_m2` when a feature's display geometry becomes `null`.
Properties are unchanged.

A first attempt the same day rounded to 6 decimals and kept finer precision
for parts that rounding invalidated. It left 2.3 MB (Brotli), and its
invalid parts traced to sub-metre necks, not to real map features. An audit of
the 5-decimal grid on that pre-rounding export bounded every change. No snapped
outline point is more than 0.68 m from the original. The 104 removed parts are
at most 1.23 m wide, the 47 filled holes at most 1.46 m wide, and the 73 neck
splits at most 1.0 m wide. Edge displacement averages 0.19 m regardless of
feature size.

Recorded after the 2 m width rule below: 0 collapsed features; 85 features
changed part or hole counts (3 map, 7 Tier 1B, 75 housing). Every coordinate is
on the grid. Uncompressed JSON is 13.1 MB (was 26.3), gzip 2.8 MB (was 9.3),
and Brotli 1.13 MB (was 5.6).

`make prepare` also regenerates `data/tier1b-municipal.json` from all three
original Tier 1B stages, reading the ingest database without changing it.
The sidecar retains all derived municipal stages. The website selects the
furthest populated original map stage per RPC, with no per-town fallback.
This spatial rule applies only to Tier 1B, not interim municipality memberships.

Geometry is projected to EPSG:32145 meters and repaired in a temporary copy.
Connected polygon parts smaller than 1 m² are removed before assignment and
after closing. Holes are not treated as standalone fragments. Since October 6,
2026 (`TIER_RULES` version 3, `HOUSING_RULES` version 6), parts that vanish
under a 1 m inward buffer are also removed at both points
(`minimum_width_m` 2). An area minimum alone kept long hairline strips, such
as a 400 m × 1 m strip of 400 m². Removed parts record `reason` `area` or `width`.
A municipality qualifies when a connected intersection reaches its interior
beyond a 75 m inward boundary band. One qualifying town receives the whole
source part, including minor border protrusions. Multiple qualifying towns
receive their intersections; each remaining connected spillover goes to the
qualifying split nearest its centroid, with GEOID as a deterministic tie-breaker.
Parts with no qualifying municipality remain in the audit, not the displayed map.

Assigned parts are unioned per RPC/GEOID/stage and closed with a 1.5 m positive
then negative buffer, followed by validity repair and polygon extraction. No
final municipal clipping is performed. Validity is checked before publication.
Unrecoverable operations stop preparation without replacing the previous file.
Raw geometry and all original stage views remain unchanged.

The sidecar records snapshot, input SHA-256, versioned rules in `config.py`,
source lineage, removed-part areas, unassigned geometry (projected WKB), source
validity repairs, and areas before/after closing. Export rejects stale preparation.
Increment `TIER_RULES.version` when changing the algorithm. Revalidate output
when changing spatial-library versions.

The current derivation has 182 municipal stage records (109 pre-application,
41 application, 32 approved); 100 are selected for the working map. It removes
146 sub-1 m² parts totaling 47.756 m² across stages. The audit retains 21 parts
with no qualifying municipality totaling 32,756.366 m² across stages.
Proctor's approved shape retains approximately 9,637 m² inside Pittsford's
reference boundary, while Pittsford has no assigned approved/application record.

`analyze.py` reads DuckDB in one read-only transaction and validates the prepared
membership file against the capture, rule values/version, and input fingerprint.
It serializes a complete generation before replacing `out/dashboard/data`.
Replacement failure restores the previous directory. Use one local writer at a
time: directory replacement has a short missing-path window and is not a
crash-durable publication protocol.

All datasets carry `schema_version`, `snapshot_id`, `captured_at`, `exported_at`,
`source_view`, and `source_urls`. `manifest.json` lists the registered datasets.
`interim-areas.json` (schema 1) contains counts and ordered municipality groups
with all source features and true/false/null eligibility and criteria. Geometry
is excluded. `map.json` (schema 2) contains separate GeoJSON collections for
areas, towns, and RPCs, plus the prepared relationships and membership provenance.
The map and table retain their existing public schemas.

The page builder checks matching snapshot/capture/export identities before
embedding CSS, JavaScript, logo, and vendored Leaflet. The page fetches table and
map JSON from the adjacent `data/` directory and validates their schema and matching
capture/export identities before rendering. Finished HTML replaces the previous
page only after build validation succeeds. Serve the complete dashboard directory
over HTTP; street tiles remain an optional online resource.

Display order is municipality A–Z, then downtown districts, village centers/buffers,
and town/growth/development areas, with names A–Z within each category. Filters
recompute visible row spans and counts without changing order. Yes is pale blue,
No pale red, and Unknown gray. Publisher eligibility is never recalculated.
Infrastructure summarizes water/wastewater/soils with three-valued OR; development
areas display zoning as not separately required while retaining the source null.

### Housing growth comparison — October 5, 2026

The question is whether mapped Tier 1B represents the geography planned for
housing growth. Housing growth includes future land use codes `VA` (Village
Area), `VC` (Village Center), `PGA` (Planned Growth Area), and `DC` (Downtown
Center). The opening map uses one color family, from lightest `VA` to darkest
`DC`. Category pieces retain their source identity for display; analysis groups
nearby pieces across categories into growth blocks within each municipality.
Pieces within 100 m (`HOUSING_RULES.grouping_gap_m`) are connected to bridge roads
and mapping gaps, with chaining allowed. The grouping buffer is intersected back with the original
prepared shapes, so the gap helps identify a block without adding gap acreage.

The comparison selects the furthest populated original FLU stage per RPC,
including non-housing FLU records when determining whether a stage is populated.
Tier 1B retains its separately selected regional working stage. Neither selection
falls back per town or combines historical stages. Selected FLU and Tier 1B stages
are reported separately, together with comparison completeness. A stage mismatch
is a comparison limitation, not evidence of a historical gain or loss.

Pipeline stage uses text in hover details rather than a second color system.
Source submission version, LURB status, and LURB action date are preserved through
source lineage and remain distinct from map stage. Coverage describes **mapped
Tier 1B representation**, not legal eligibility, final approval, or the date an
area became Tier 1B. Spatial results cannot establish whether a proposed boundary
is permitted by law.

Preparation reads the saved database without changing it. It reuses the municipal
Tier 1B assignment approach (projected meters, interior qualification beyond a
boundary band, audited fragments and spillover), explicitly for this new FLU
analysis. It does not change approved interim-area memberships. Raw source
geometries, all original stages, excluded fragments, failed/unassigned source
records, and lineage remain available.

Coverage is measured on detailed prepared geometry in EPSG:32145. Tier 1B is
unioned before intersection so overlapping source records cannot inflate the
covered area. Each block retains total area, covered area, and covered fraction.
Block outcomes are substantial, partial, none, or unknown. A municipality with
every block substantially represented is `all`; mixed block outcomes or a
materially partial block are `some`; all blocks without meaningful coverage are
`none`. Municipalities without growth blocks are `no_housing`; incomplete inputs
use `unknown` rather than appearing as no Tier 1B coverage.

The reverse diagnostic measures Tier 1B area outside the selected housing growth
union. It retains outside area/fraction and source stages, using area and fraction
tolerances to distinguish meaningful differences from edges. This is an audit
result: proposed stages can change during review, stage mismatches can explain
differences, and the diagnostic does not declare a legal violation. It is retained
without introducing a separate application workflow.

Comparison uses selected regional unions, avoiding false uncovered borders when
FLU and Tier 1B protrusions receive different municipal ownership. Municipal
ownership still follows the recorded assignment rules. Valid polygon components
with no qualifying municipality remain context outside the analytical population;
they do not create uncertain municipal classifications. Missing housing
geometry or absent selected FLU classifications cannot be localized reliably and
make the affected RPC uncertain. Known non-housing FLU with absent geometry does
not hide a housing block. Non-housing codes such as `RD`, `WA`, and `X` remain
outside the four-category selection even if no display-name mapping exists.
Complete FLU establishes `no_housing` even if Tier 1B is
unavailable; missing Tier 1B prevents classification of existing growth blocks.

`data/housing-growth.json` is the derived sidecar; the independent public
`out/dashboard/data/housing-growth.json` uses schema 1. Its `categories`, `blocks`,
`coverage_parts`, `tier_outside`, and retained `context_fragments` are GeoJSON collections.
`municipalities` is a lightweight
summary array keyed by official GEOID; `sources` provides FLU source feature/object/
layer identifiers and publisher stage/status fields. `tier_sources` provides the
separate Tier 1B lineage; `tier_source_indices` link diagnostic features to that
array, while category/block `source_indices` link to FLU `sources`. `selected_stages`,
`tier_selected_stages`, `reverse_diagnostics`, `sensitivity`, versioned `rules`,
input fingerprint, and preparation audit make the analysis inspectable.
The full projected-WKB audit remains in the sidecar; the public export carries
audit counts and a pointer/fingerprint identifying that prepared provenance.
Public geometry uses the same guarded 0.5 m display simplification as Tier 1B,
with per-part and whole-feature fallbacks recorded. Complementary covered and
uncovered pieces of a split block retain their detailed geometry to preserve
their shared boundary; single-piece blocks use the guarded simplification.
Areas and classifications are
copied unchanged from preparation, never measured from simplified browser
coordinates. The manifest registers this dataset, and page assembly and browser
loading validate its schema and generation alongside the existing exports.

Municipality assignment, block connectivity, substantial coverage, and meaningful
reverse differences use separate controls because they address different errors.
These analytical thresholds are provisional methodology choices; the sidecar
records their exact values and sensitivity results. Borderline examples and
changes under nearby thresholds must be inspected before interpreting a
municipality's classification as a substantive planning difference. Changing
rules invalidates the prepared fingerprint and requires `make prepare`.

October 5, 2026 audit update: `TIER_RULES.version` advances to 2 to record source
geometries whose repair/extraction yields no polygonal parts as an explicit
preparation failure. The existing 75 m qualification, 1.5 m closing, 1 m² fragment
minimum, splitting, and spillover geometry rules are unchanged. Housing
preparation fingerprints the Tier processing rules separately from its own rules
so either derivation's rule changes invalidate the comparison sidecar.

Initial provisional controls reuse the 75 m interior band, 1.5 m closing radius,
and 1 m² fragment minimum. A coverage discrepancy is tolerated when it is at most
1% of its block, or when it is both at most 5% and at most 1,000 m². Substantial
coverage tolerates that amount of uncovered area; no coverage tolerates that
amount of covered area; other blocks are partial. The reverse diagnostic has
independent controls with the same initial tolerance: 1% of total Tier 1B area,
or both 5% and 1,000 m². Every measured outside difference remains available,
including those below the flagging threshold. Sensitivity compares
tighter limits (at most 1% **and** 250 m², without the independent 1% allowance)
and looser limits (2%, or both 10% and 2,500 m²), retaining changed block IDs and
counts rather than silently changing the baseline classification. These are
analytical tolerances, not statutory thresholds.

Grouping investigation, October 5, 2026: regrouping the detailed prepared union
with gaps of 0, 10, 20, 30, and 50 m produced 810, 761, 514, 485, and 457 statewide
blocks respectively. Bristol's corresponding counts were 34/28/3/2/2;
Middlebury's were 35/32/5/3/3; Vergennes's were 49/43/4/4/2. The initial 30 m rule
reduces fragmentation across roads while keeping separations that a 50 m rule
would merge. Its 485 block geometries are valid and preserve the underlying
prepared union area, 538,717,287.115 m². This evidence supports a provisional
grouping choice; changing the gap can change block-based municipal summaries.

Grouping revision, October 5, 2026: at statewide scale, 30 m left adjoining
pieces of one settlement as separate Housing Growth Areas. Regrouping the same
selected stages gave 485, 443, 406, 394, 392, and 385 blocks at 30, 60, 100, 150,
200, and 400 m. Most merging happens by 100–150 m: at 100 m Fair Haven, West
Rutland, Vergennes, and Barre City go from 4–5 blocks to 1. The step from 100 to
150 m merged 10 more pairs or triples (gaps of 100–147 m), including two large
Castleton areas (476.9 and 444.0 acres) and three in Colchester; every merged piece
already shared its coverage status. On review, 100 m was preferred so those stay
separate. Going from 150 to 400 m merged only 9 more, including Bristol,
Middlebury, and Shelburne, where some blocks are separate villages.
`HOUSING_RULES` version 5 adopts 100 m. Prepared union area is unchanged at
538,717,287.115 m², and municipal outcomes are unchanged at every tested gap
(87 all, 13 some, 133 none, 23 no housing growth areas). The 406 blocks classify as
157 substantial, 9 partial, and 240 none, and all are comparable.

Recorded October 5, 2026 before the boundary-context revision, for saved capture
`20261005T155533.479832Z`: the selected
housing sources comprise 745 FLU records. The 485 blocks include 199 substantial,
8 partial, 258 without meaningful coverage, and 20 unknown blocks. Municipality
summaries are 84 all represented, 12 partly represented, 131 none represented,
23 without housing growth areas, and 6 unknown. Independent read-only DuckDB
checks matched all selected FLU source IDs/layers, publisher versions, statuses,
dates, and nulls, plus all 553 retained Tier source lineage records.

No reverse difference exceeds the initial meaningful-portion tolerance in this
capture. The largest measured outside area is Hyde Park's approved comparison:
3,385.016 m², or 0.226% of its mapped Tier 1B area. The complete diagnostic retains
this difference rather than treating tolerated edges as geometrically identical.
Tighter coverage tolerances change three blocks and looser tolerances change
one; neither changes the municipal all/some/none summaries in this capture.
These observations describe the saved capture and provisional method, not a
legal determination or a live application status.

#### Boundary fragment review — October 5, 2026

After inspecting the retained boundary fragment, the user identified the orange
component in Saint Albans City as an overhang of Saint Albans Town's housing
growth area caused by mismatched boundary datasets. The observed source is
`21062efe90373f63:21295`, connected part 1, approved `PGA`, in capture
`20261005T155533.479832Z`. This explanation motivates generic boundary-mismatch
handling. It does not install a source-ID, part-ID, or municipality exception.
Display geometry and source lineage remain available while a general geometric
rule determines whether a fragment participates in analysis.

The revised processing decision reuses the existing 75 m municipal
interior-qualification rule to define the analytical population, recorded in
`HOUSING_RULES.version` 2. Valid polygon components recorded as
`no qualifying municipality` stay outside analysis and do not make an entire
municipality uncertain. There is no additional thinness, proximity, area-budget,
source-ID, or municipality exception. Missing geometry, geometry that cannot
yield polygonal parts, and unusable source-stage comparisons remain uncertain.

Excluded components retain their complete prepared shape in the additive
schema-1 `context_fragments` collection, with source indices, source category and
stage, original projected-geometry SHA-256, area, `context_reason`, and
`analytical_included: false`. They remain saved context and do not become
growth blocks, contribute housing acreage, or enter coverage denominators.
The complete preparation audit retains their original component and processing
decision. Valid unassigned Tier 1B components follow the same population rule.
Tier comparison geometry excludes the context mask outside accepted housing
geometry so reverse diagnostics use the same population; original Tier display
geometry stays intact and excluded comparison area is recorded separately.
`boundary_context` records the qualification basis, excluded FLU component count
and area, and Tier source-part/hash adjustment records. Reverse diagnostics retain
`display_tier_area_m2`, `analytical_excluded_m2`, and the adjusted `tier_area_m2`
so the population change can be reconciled without rewriting display geometry.
This processing decision defines the population being compared, not the intent
behind every excluded polygon. In particular, Derby's isolated Village Area
component is excluded by the same existing qualification rule; it is not labeled
a mapping artifact merely because it is separate from the other housing areas.

Recorded October 5, 2026 after this revision, using the same saved capture:
all six previously uncertain municipalities are resolved. Vergennes, Saint
Albans City, and Derby are `all`; Essex and East Montpelier are `none`;
Woodstock is `some`. Statewide results are **87 all, 13 some, 133 none, 23
no housing growth areas, and 0 unknown**. The 485 unchanged analytical blocks
classify as 207 substantial, 9 partial, and 269 without meaningful coverage.

The context collection retains 19 original FLU components totaling
36,126.924 m²; their source-part identifiers, projected geometry hashes, and
areas reconcile with the prior audit. Eleven selected unassigned Tier components
totaling 23,190.172 m² are excluded by the same existing qualification rule.
The context mask removes a further 2,056.100 m² from the assigned Tier comparison
geometry. Each adjusted Tier area plus its recorded excluded area reconciles
with the original display area within 0.000002 m². No meaningful reverse
difference remains; the largest measured difference remains Hyde Park at
approximately 3,385.016 m², or 0.226%.

Before/after checks confirm identical block identifiers, block shapes, housing
area denominators, category geometry, source lineage, and selected stages.
Clipping and projected-coordinate round trips change covered-area measurements
by at most 0.001363 m² (verified below a 0.01 m² numerical tolerance); no
previously classified municipality changes category. All six municipal changes
come from resolving the prior unknown classifications. The raw database SHA-256
is unchanged. Tighter and looser coverage sensitivity checks leave the resulting
87/13/133 all/some/none counts unchanged.

#### Story presentation revision — October 5, 2026

The map omits excluded boundary fragments. Their `context_fragments` data,
original geometry hashes, and audit records remain available for research;
this presentation change does not alter the analytical population or public
data contract. The story has four chapters: land-use categories, municipalities
with included growth areas, block coverage by mapped Tier 1B, and municipal
Tier 1B coverage.

The added municipality chapter distinguishes **233 municipalities with included
growth blocks** from **23 with no included growth areas**, accounting for all
256 reference municipalities. In this saved capture, `no_housing` corresponds
exactly to zero included blocks. This describes the selected mapped stages and
analysis population; it is not a claim that those municipalities never had
growth areas historically.

“Cannot assess” is shown only when the loaded municipal or block classifications
contain unknowns; the current capture has none. “No included growth areas” stays
distinct from no Tier 1B coverage. Independent checks agree between prepared
and public exports: all 256 municipalities, 485 blocks, and 100 reverse
comparisons are comparable. The 403 category features have known selected FLU
classes/stages and valid source lineage; they do not carry a separate analytical
comparison status. Publisher approval nulls remain source-stage details rather
than implying an unknown spatial comparison.

#### Coverage polygon presentation — October 5, 2026

The overlap chapter now displays actual spatial portions rather than assigning
one fill color to each entire growth block. `coverage_parts` contains the
intersection of each block with the selected regional Tier 1B comparison union
(`coverage_kind: covered`) and its difference (`uncovered`). Empty portions are
omitted, but positive-area differences are not removed by the classification
tolerances. Covered geometry is green and uncovered geometry is red. Unknown
comparisons, when present, retain the whole block as an unknown portion.

Each portion preserves its parent's `block_id`, stage, comparison status, source
lineage, block `area_m2`, covered area/fraction, and block classification.
`portion_area_m2` records the area of that particular covered or uncovered shape.
Hover details distinguish portion acreage from total block acreage.
`HOUSING_RULES.version` 3 invalidates preparation for this added geometry;
the additive public contract retains schema 1.

Yellow is reserved for municipalities classified `some`. A meaningful partial
block or a mixture of represented and unrepresented blocks yields a yellow
municipality; every block substantially represented yields green, while no
meaningful block coverage yields red. Existing small-difference tolerances govern
these municipal summaries, independently of the exact green/red portion shapes.
The four-chapter sequence and analytical population stay unchanged.

The drawable partition is constructed in WGS84 from the valid parent block and
Tier comparison geometry. Constructing polygon overlays in projected coordinates
and then transforming their vertices independently can create invalid rings in
browser coordinates, especially along nearly coincident edges. Projected
analytical areas and block classifications remain authoritative and unchanged.
`coverage_display` records numerical portions that collapse to an empty browser
representation; their original projected areas and geometry remain in the audit.
These are serialization outcomes, not classification-tolerance exclusions.

Export preserves both detailed display shapes whenever a block has covered and
uncovered portions. Simplifying their common edge independently could introduce
gaps or overlaps. Whole-block covered/uncovered/unknown portions use the existing
guarded display simplification. `display_simplification.coverage_parts_policy`
and `retained_split_block_ids` record that choice; analytical areas and statuses
are copied unchanged.

Recorded October 5, 2026: the final drawable collection has 561 valid WGS84
features, 224 covered and 337 uncovered. Projected analytical totals remain
374,241,321.923 m² covered and 164,475,965.190 m² uncovered. The audit retains
147 numerical portions with empty browser geometry, totaling 0.000422 m² of
original projected area. Municipal outcomes remain 87 all, 13 some, 133 none,
23 no included growth areas, and 0 unknown.

Covered and uncovered display pieces have no overlapping area. The largest
reconstructed block difference is 2.204 m² and the largest display-versus-analysis
portion-area difference is 3.521 m². These minor coordinate/overlay differences
are acceptable for the statewide visualization; no additional precision
handling is introduced. Block shapes, analytical areas, classifications, source
lineage, and the raw database remain unchanged.

#### Coverage sliver absorption — October 5, 2026

Supersedes the WGS84 paired display partition above. Growth and Tier 1B maps
trace nearly identical edges, and the exact partition contained 2,120 uncovered
polygon pieces, 1,781 of which vanish under a 2 m inward buffer (about
5,210 m² in total); covered pieces had 515 such slivers. They flickered as
red hairlines at most zoom levels.

`split_housing_block` now partitions each block once in EPSG:32145. Every
covered or uncovered piece narrower than twice `HOUSING_RULES.coverage_sliver_m`
(2 m) joins the kind of its largest wider neighbor, or keeps its own kind when
it has none. Pieces come from one overlay and share exact edges, so merged
portions tile the block without subtraction residue. The projected portions
are transformed for display, with a validity repair for float-precision ring
contacts. `covered_m2` and `coverage_fraction` measure the absorbed portions;
`exact_covered_m2` retains the unadjusted intersection. `HOUSING_RULES.version`
4 invalidates earlier preparation; `coverage_display` and
`audit.coverage_display_omitted_parts` are no longer produced.

Recorded October 5, 2026: 502 drawable features, 216 covered and 286 uncovered.
Covered area is 374,245,907.844 m² against 374,241,321.923 m² exact
(+4,585.9 m²). No block coverage status or municipal outcome changed: 87 all,
13 some, 133 none, 23 no included growth areas, and 0 unknown. Of 361
uncovered polygon pieces, 18 are specks under 0.01 m² inside tiny blocks or
touching neighbors at a point, and 4 (10–115 m²) are narrow uncovered areas with
no wider neighbor. Only 17 blocks remain split for display, so the public
export's coverage collection is 6.4 MB.

Nearest-piece absorption and minimum width (October 6, 2026): six fully
covered blocks still published uncovered portions of 0–0.005 m². Separately,
31 thin pieces stayed unmerged. Some missed a wide neighbor by float noise
(about 2×10⁻⁸ m), because intersection and difference are separate overlays.
Others were up to 55 m from any wide piece, touching only other thin pieces. A
thin piece now joins the kind of the *nearest* wider piece in its block (the
largest when several touch). Geometry is never moved, so kinds still tile the
block. The 2 m width rule removed 104 housing parts (2,242 m²; largest 800 m²)
and 143 Tier 1B parts across all stages (3,145 m²). Blocks dropped from 406 to
405, removing a 2 m² block (`AC:5000144350:pre_application:2`). Context
fragments dropped from 19 to 12, and coverage portions from 421 to 414. 27
blocks changed area by 2,132 m² in total (largest 800.6 m²). No block coverage
status or municipal outcome changed: 87 all, 13 some, 133 none, 23 no
included growth areas, and 0 unknown. Tier 1B stage counts and municipality
memberships are unchanged.

#### Housing Growth Area presentation — October 5, 2026

The story now calls each prepared block a **Housing Growth Area**: Downtown
Center, Village Center, Planned Growth Area, and Village Area polygons within
the grouping gap (100 m since rules version 5) in one municipality. The opening
chapter outlines blocks over their category polygons and counts blocks, not
municipalities. The overlap chapter counts blocks by `coverage_status` (“Covered
by Tier 1B”, partly covered, not covered). Municipal hovers list every nonzero
block outcome, so a partly covered block is never reported as uncovered. Areas crossing a municipal line remain one
block per municipality, as in the analysis.

Wording revision, October 6, 2026: story labels and hovers say “mapped as
Tier 1B” instead of “covered by Tier 1B,” and the municipal chapter is titled
“Tier 1B designation by municipality” (full, partial, or no designation).
Export fields and classifications are unchanged.

Hovers report one **submission stage**, the selected regional `map_stage`
(pre-application, application, or approved). In this snapshot the selected FLU
and Tier 1B stages match in every RPC, and source fields follow the stage
exactly: pre-application records are `PRE` with no LURB status; application
records are `APP`, with LURB status null (BCRC) or `RCV` (MARC); approved records
are `APP` with LURB status `APR` and an action date. Submission version, LURB
status, and date remain in source lineage and are no longer shown. If the FLU and
Tier 1B stages ever differ, municipal and coverage hovers name both.

The reverse diagnostic and comparison-status notes are no longer displayed; none
applied to this snapshot (0 meaningful diagnostics, all blocks comparable).
Both remain in the export, and unknown classifications still appear in keys
when present.

The browser hides covered or uncovered pieces under one acre when their block
has more than one piece. With 30 m grouping this hid 12 pieces (largest
111.0 m², total 198.3 m²); with 100 m grouping it hides 7 (1 covered, 6 uncovered;
2.0 m² in total), and no whole block is under one acre. The export, block areas,
and classifications are unchanged.

The export adds `municipalities[].municipality_area_m2`, measured from the saved
municipal boundary in EPSG:32145 at export time, so growth hovers can give the
Housing Growth Area share of a municipality. This additive field keeps schema 1;
all 256 municipalities have an area.
