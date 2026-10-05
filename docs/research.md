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
by preparation. The current file schema is version 1:

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

The fourth chapter overlays the working Tier 1B map in teal (#287f89),
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

`make prepare` also regenerates `data/tier1b-municipal.json` from all three
original Tier 1B stages, reading the ingest database without changing it.
The sidecar retains all derived municipal stages. The website selects the
furthest populated original map stage per RPC, with no per-town fallback.
This spatial rule applies only to Tier 1B, not interim municipality memberships.

Geometry is projected to EPSG:32145 meters and repaired in a temporary copy.
Connected polygon parts smaller than 1 m² are removed before assignment and
after closing. Holes are not treated as standalone fragments.
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
