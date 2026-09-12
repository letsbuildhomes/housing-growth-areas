# Database table and column reference

This describes **`data/act181_ingest.duckdb`**, the current ingest database.
Schema and counts were checked against the database on September 8, 2026,
for snapshot `20260908T222348.634248Z`. The older `data/act181.duckdb` belongs
to the [legacy analysis](LEGACY_ANALYSIS.md) and is outside this reference.

There are **5 stored tables and 18 views**. A view is a saved query that you
can use like a table; it does not store another copy of the data. Shared view
columns are documented once below rather than repeated for every dataset.

## Where to start

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

## `ingest_features`

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

### Additional information inside `raw_properties`

These are **JSON keys, not extra SQL columns**. Availability varies by source.
This is a selection of useful keys; the complete source-specific field list,
aliases, and coded domains are in `ingest_sources.metadata`.

| Information | Source keys currently present |
|---|---|
| Notes and alternate names | `NOTES`, `Notes`, `Comments`, `DESCRIPT`, `AreaName`, `Name`, `Town` |
| Submission and publication dates | `DATE_RPC`, `DATE_SUBM`, `DATE_AGG`, `DATE_CSA`, `DATE` |
| Submitter and designation details | `SUBMITTER`, `Submitter`, `DESIG_CS`, `DESIG_TYP`, `LU_AUTH` |
| Source acreage and measurements | `ACRES`, `Acres`, `Shape__Area`, `Shape__Length`, `Shape.STArea()`, `Shape.STLength()`, `Shape_Leng` |
| Buffer and original feature references | `BUFF_DIST`, `ORIG_FID` |
| Water/wastewater system references | `DW_System`, `DW_WSID`, `WW_Facility`, `WW_FacilityID` |
| Designation documents and renewals | `ApprovedMap`, `Renewal`, `RenewalDate`, `RENEWED` |
| Publisher edit history | `CreationDate`, `Creator`, `EditDate`, `Editor`, `created_date`, `created_user`, `last_edited_date`, `last_edited_user` |
| Organization/contact information | `OrganizationName`, `website`, `email`, `Phonenumber` |

Dates in raw JSON may be date strings or ArcGIS epoch-millisecond numbers.
Source measurement units depend on the service metadata; they are not all
standardized acreage. Alternate source names such as `Name` and `Town` are
preserved here even when they do not populate the normalized name columns.

## `ingest_layers`

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

## `ingest_sources`

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

## `ingest_memberships`

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

## `ingest_runs`

**Capture history and reproducibility information.** One row per successfully
loaded capture. Currently **1 row**. Primary key: **`run_id`**.

| Column | Type | Meaning / examples |
|---|---|---|
| `run_id` | VARCHAR | Unique UTC capture identifier. |
| `started_at` | TIMESTAMP WITH TIME ZONE | When source discovery/download began. |
| `completed_at` | TIMESTAMP WITH TIME ZONE | When capture finished, before database loading; not a source publication date. |
| `snapshot_path` | VARCHAR | Absolute path to the saved snapshot directory. |
| `manifest` | JSON | Capture manifest: schema version, timestamps, CRS, source/layer inventory, membership IDs, and file checksums. |

## Views: current data and map-ready records

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

## Views: individual datasets

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
table export. Its local `municipality_membership.py` derivation uses normalized
source labels plus the approved municipality crosswalk, not intersections.
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
export for review, with no spatial fallback.

The approved September 12, 2026 derivation yields 319 areas, 320 memberships
(Jericho–Underhill has two), 187 municipalities with areas, 118 with a likely
eligible area, 69 with areas but none likely eligible, and 69 without areas.
Rutland City overrides are limited to the three reviewed source features;
Tyson maps to Plymouth. The table still groups 194 original source labels.
See `MUNICIPALITY_MEMBERSHIP.md` for the approved review record.

The UI groups water, wastewater, and soils as infrastructure alternatives. Its
display-only summary is true if any value is true, false if all are false, and
null otherwise. It does not replace `likely_eligible`. For the
`town_growth_development` category, the table displays “Not separately required”
for zoning and the hover omits zoning; the exported source null is unchanged.

## Relationships and interpretation

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
See [SOURCE_INVENTORY.md](SOURCE_INVENTORY.md) for coverage and source caveats.

## Example queries

Run `LOAD spatial;` once per DuckDB connection before using spatial functions
(the extension is already installed in the project's current environment).

```sql
-- Eligibility, criteria, and geometry for each interim area.
SELECT name, likely_eligible, zoning_bylaws, drinking_water,
       sewer_wastewater, adequate_soils, ST_AsGeoJSON(geom) AS geometry
FROM interim_areas;

-- Access a source attribute that has no dedicated column.
SELECT rpc, tier_code, raw_properties->>'NOTES' AS source_notes
FROM tier_approved;

-- Find each logical layer's source and published record count.
SELECT l.rpc, l.kind, l.stage, l.feature_count, s.url
FROM current_layers l
JOIN ingest_sources s USING (run_id, source_id)
ORDER BY l.rpc, l.kind, l.stage;
```
