# Source inventory — September 8, 2026

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

## Interim exemption areas

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

## FLU and Tier 1B stage views

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

## Retained source irregularities

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
