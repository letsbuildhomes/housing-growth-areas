# Working in this repository

## Purpose and orientation

Let's Build Homes uses this Vermont Act 181 research project to inspect public
interim Act 250 exemption areas, future land use (FLU), and tier designations.
The current product is a static HTML table dashboard; a mapping mode is a future
extension. Read `README.md` for commands/layout, `DATA_DICTIONARY.md` for schemas,
and `SOURCE_INVENTORY.md` for dated source findings.

## Preserve the saved research data

- Normal website work must use the existing `data/act181_ingest.duckdb` in
  read-only mode. Do not download or re-ingest data unless the user explicitly
  requests fresh source data or authorizes initial data acquisition.
- `make`, `make build`, `make export`, `make serve`, and `make rebuild` must never
  depend on ingestion. `make ingest` / `make extract` are explicit network paths.
- `make clean` removes only `out/dashboard`. Preserve `in/`, `data/`, completed
  snapshots, and the legacy outputs during normal work.
- Data directories are Git-ignored. If data is missing, report that and look for
  a saved database/snapshot. Do not silently create an empty database or substitute
  sample data. A completed snapshot can be restored with
  `uv run python extract.py --snapshot <directory>` without downloading.
- Do not modify raw snapshots or their checksums to conceal discrepancies.

## Architecture and edit locations

- `export_data.py`: current read-only queries and the `EXPORTERS` registry.
  Add datasets here; export version, snapshot provenance, and boolean/null values
  must be preserved. Current output: `out/dashboard/data/*.json`.
- `build_dashboard.py`: embeds the selected JSON, styles, and scripts into
  `out/dashboard/index.html`. `web/` contains the editable HTML/CSS/JavaScript.
  Never hand-edit generated output as the implementation.
- The standalone page must work offline, without a database server or external
  assets. It embeds JSON, so rebuilding the page is required after export changes.
- Keep future map geometry exports separate from table-only datasets. Do not
  add a runtime backend or frontend framework merely to add another view.
- `ingest.py` defines current database tables/views and snapshot loading;
  `ingest_sources.py` and `arcgis.py` handle public source discovery/downloads.
- `config.py` contains shared normalization dictionaries but also legacy settings;
  its `DB_PATH` is **not** the current ingest database.
- `transform.py`, `analyze.py`, `legacy_extract.py`, and `legacy_status.py` belong
  to the old overlap analysis documented in `LEGACY_ANALYSIS.md`. Do not route
  the current dashboard through that pipeline.

## Data and display conventions

- Group interim areas by recorded municipality, normalize only whitespace/case,
  and preserve each feature. Do not silently remap localities or merge records.
- Sort municipality A–Z; within each group sort downtown districts first,
  village centers/buffers second, and town/growth centers/development areas third;
  then sort alphabetically by area name within category.
- Municipality cells span their visible area rows. Filtering must recompute
  row spans and displayed counts without changing the established sort order.
- Yes is pale blue, No pale red, Unknown neutral gray. Missing criteria are NULL,
  not false. All five fields (eligibility plus four criteria) retain this distinction.
- Label interim status as **likely interim Act 250 exemption eligibility**,
  not Tier 1B eligibility/approval. Use the publisher's status rather than
  recalculating legal eligibility from criteria.
- Submission version (`APP`), LURB approval (`APR`), and map stage are distinct.
  Submitted and approved services/views can overlap. Source IDs and row counts
  are not necessarily unique real-world areas or historical geometry versions.
- Preserve raw metadata and source geometries. Missing/invalid geometry and
  unmapped records remain available; any later geometry repair should be a
  documented derived result, not an overwrite of the source geometry.
- Source inventory counts are dated observations, not constants for future captures.

## Validation and collaboration

- Prefer `apply_patch` for routine edits. Show small, concrete examples when
  explaining code changes, alongside the relevant behavior.
- Run `make test` for logic changes and `make build` for export/page changes.
  Reconcile exports with DuckDB; verify grouping, ordering, null handling, and
  filter/reset behavior when those parts change. Documentation-only edits do
  not require an ingest or a full application test run.
- Use `uv run python build_dashboard.py` for a page-only rebuild from existing
  exports. Preview with `make serve`; reload after rebuilding. Avoid starting a
  duplicate preview server if an existing one already serves this output.
- Keep the README, data dictionary, and export contract aligned with changes.
  Update only the relevant documentation; preserve historical findings as dated.
- No routine approval checkpoint is needed for authorized, reversible local
  edits. Keep work scoped to the user's requested dashboard/data improvements.
