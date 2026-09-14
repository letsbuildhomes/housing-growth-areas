# Working in this repository

Read `README.md` for commands and layout, and `docs/research.md` for data contracts,
source findings, and approved municipality decisions.

## Preserve research data

- Normal builds use `data/act181_ingest.duckdb` read-only. Never download or reload
  research data unless the user requests a refresh or snapshot restoration.
- Build/export/serve/rebuild must never depend on acquisition. `make extract`
  and `make ingest` are explicit network paths; `make transform SNAPSHOT=…` is
  explicit offline loading. `make prepare` only regenerates the derived sidecar.
- Clean removes only `out/dashboard`. Preserve `in/`, `data/`, and other saved
  outputs. If data is missing, look for a saved database/snapshot; never silently
  create an empty database or sample data.
- Never overwrite raw geometry/metadata or edit snapshot checksums. Missing,
  invalid, and unmapped records remain available. Derived repairs need provenance.

## Code and display contracts

- Keep UI copy spare. Do not add decorative step labels or repeat navigation
  instructions (for example, “Vermont in three steps,” “Step 1 of 3,” and
  “Scroll to continue or use the steps below”). Use one purposeful scroll cue
  beside navigation; let the visual progress indicator communicate progress.

- Keep production Python in `extract.py`, `transform.py`, `analyze.py`, `config.py`,
  and `arcgis.py`. Prefer functions in their owning stage over new helper modules.
- Edit `web/` and the source scripts, not generated output. The standalone table
  and polygons work offline; only the optional street tiles require internet.
- Preserve public export versions, capture provenance, source IDs, and boolean/null
  distinctions. Keep map geometry separate from the lightweight table export.
- Group source municipality labels using case/whitespace normalization only;
  retain every feature. Sort towns A–Z, then downtown, village/buffer, and
  town/growth/development categories, then area names A–Z. Filtering recomputes
  visible row spans/counts without changing order.
- Yes is pale blue, No pale red, Unknown gray. Use the publisher's **likely interim
  Act 250 exemption eligibility**, not a recalculated status or Tier 1B approval.
- Submission version, LURB approval, and map stage are distinct and can overlap.
  Source IDs/counts do not guarantee unique real-world areas or historical versions.
- Prepared membership uses approved config rules and provenance validation;
  unmatched labels stop preparation. Never silently use spatial intersections.

## Validation and documentation

- Prefer `apply_patch` for routine edits; include small concrete examples when
  explaining code changes. No routine approval checkpoint is needed for authorized
  reversible local changes.
- Run `make test` for Python logic changes and `make build` for export/page changes.
  Browser checks live in `tests/browser.html`; do not add a Node requirement.
- Reconcile changed exports with DuckDB. Check filters/reset, grouping/order/nulls,
  map interactions, and narrow layouts when changing those behaviors.
- Use `make page` for page-only rebuilds. Reuse an existing preview server; reload
  after rebuilding. Documentation-only edits need link/command checks, not ingest.
- Keep instructions in README and research details in `docs/research.md`. Avoid
  duplicating generated inventories or creating a document for each feature.
  Preserve dated findings and the evidence behind approved exceptions.
