# Vermont Act 181 research

Let's Build Homes research on interim Act 250 exemptions, future land use, and
tier designations. The output is a standalone map and table dashboard.

## Run

Requires Python 3.9+, `uv`, and GNU Make 4.3+ (grouped output targets). No Node, npm, or frontend build tool is needed.

```sh
uv sync --locked
make setup-spatial      # one-time DuckDB extension installation; needs network
make                    # build from the saved database, without source downloads
make serve              # preview at http://127.0.0.1:8000
make test               # Python regression checks
```

A clone does not include research data: `in/`, `data/`, and `out/` are Git-ignored.
Copy the saved `data/act181_ingest.duckdb` or restore a completed snapshot.
Missing data produces an error; it never triggers acquisition or sample data.

| Command | Action |
|---|---|
| `make` / `make build` / `make analyze` | Prepare relationships, export JSON, build HTML from saved data. |
| `make extract` | **Network:** capture raw sources only, into a dated snapshot. |
| `make transform SNAPSHOT=in/snapshots/<capture>` | Load that completed snapshot offline and prepare relationships. |
| `make ingest` | **Network:** capture, load, and prepare in sequence. |
| `make page` | Rebuild HTML only when its source files or exports changed. |
| `make export` / `make prepare` | Update JSON exports / derived membership and geometry sidecars when their inputs changed. |
| `make status` | Show saved capture coverage and quality flags. |
| `make serve PORT=8001` | Build and preview on a chosen port. |
| `make deploy` | Build from saved data and publish the dashboard to vibes. |
| `make clean` / `make rebuild` | Remove / rebuild only `out/dashboard`. |
| `make test` | Run Python tests under `tests/`. |

`WORKERS=1` through `8` controls capture concurrency (default 4). `HOST` controls
preview binding (default `127.0.0.1`). Use `make help` or a script's `--help` for
options. Reuse an existing preview server; after source edits, rebuild and reload.
Make uses file modification times: unchanged builds skip preparation, exports,
and HTML. Database, preparation code, configuration, dependency files, and the
Makefile invalidate sidecars; export code also invalidates exports. Changes under
`web/` rebuild HTML only. Missing members of an output group regenerate the whole
group once, including with `make -j`. `make page` requires existing exports and
never prepares or exports data. Use `make -B build` to force every build stage;
Make bypasses spatial fingerprint shortcuts when preparation runs. Direct Python
commands do not use Make's timestamps; spatial preparation retains its fingerprint
shortcuts unless `transform.py --prepare --force` is requested.
Run `make build`, then upload the contents of `out/dashboard/` to your website
directory, keeping `index.html` and its `data/` folder together. Paths are relative,
so publishing in a subdirectory works. CSS, JavaScript, and the logo remain embedded;
table and map JSON load from `data/`. No backend is required.
Builds write compact JSON without indentation; enable gzip or Brotli on the web
server to further reduce download sizes.
Tier 1B and housing growth display polygons use guarded 0.5 m simplification during export. Detailed
prepared geometry remains unchanged for analysis; export metadata records the
rules and automatic fallbacks. All exported map geometry is then snapped to a
0.00001° grid (about 1 m); export fails if snapping moves a vertex more than
1 m or changes any piece 2 m or wider.
Preview with `make serve`; opening the HTML directly via `file://` cannot load JSON.
Polygons and the table work on a local server without internet; optional
OpenStreetMap tiles need internet.

For preview access from another machine on the network, run
`make serve HOST=0.0.0.0 PORT=8000` and open `http://<server-network-IP>:8000/`.

## Vibes deployment

Run `make deploy` to publish at
`https://vibes.jaktiano.com/housing-growth-areas/`. It uses the existing
`VIBES_DEPLOY_HOST` environment variable and your SSH configuration; the host
must support noninteractive SSH authentication. Deployment requires `ssh` and
`rsync` locally.

The target builds from the saved database, then uploads only `out/dashboard/`
to `/srv/http/vibes/housing-growth-areas/`. It removes obsolete files within
that project directory, sets readable file permissions, and updates the remote
directory timestamp after upload. Data acquisition remains an explicit
`make ingest` operation.

## Project layout

The three stages keep raw inputs raw, prepare reusable data once, and generate
reports from prepared data. A normal build starts with the saved database;
source refresh and snapshot loading are always explicit.

```text
extract.py   → in/snapshots/<capture>/
transform.py → data/act181_ingest.duckdb + derived JSON sidecars
analyze.py   → out/dashboard/data/*.json + index.html
```

| File/folder | Responsibility |
|---|---|
| `extract.py` | Source definitions, discovery, and verified snapshot capture. |
| `transform.py` | Offline snapshot validation/loading, normalization, and membership derivation. |
| `analyze.py` | Read-only reporting queries, export publication, page assembly, and status. |
| `config.py` | Paths, publisher mappings, and approved municipality exceptions. |
| `arcgis.py` | HTTP requests, retries, pagination, and completeness checks. |
| `web/` | Editable HTML, CSS, browser scripts, logo, and vendored Leaflet. |
| `tests/` | Python regressions and `browser.html` for browser checks. |
| [Research reference](docs/research.md) | Source scope, schemas, dated findings, crosswalk decisions, export contract. |

`transform.py --prepare` reads the database without modifying it and regenerates
the membership, municipal Tier 1B, and housing growth sidecars. `analyze.py` accepts `--export`, `--page`, or `--status`;
without a mode it exports and builds. Scripts accept alternate paths through
`--db`, `--memberships`, and/or `--output` where applicable.

## Saved data and recovery

For a database saved before the working Tier 1B view was added, install that
derived view once (offline; no source records change):

```sh
uv run python3 -c "import duckdb; from config import DB_PATH; from transform import create_tier1b_working_view; assert DB_PATH.is_file(), 'Restore the saved database first'; con = duckdb.connect(str(DB_PATH)); create_tier1b_working_view(con); con.close()"
```

New snapshot loads create the view automatically. Normal builds remain read-only.

Back up the database and completed snapshots separately from Git. Stop database
writers before copying the database. Restore with `make transform SNAPSHOT=…`.
The same snapshot replaces its run transactionally instead of duplicating it;
failed loads preserve the previous successful run. Source files and checksums
are never changed by transformation. Missing/invalid geometries stay available.

A copied database can retain an old snapshot path; exporting does not require
that directory, and restoring updates the path. Prepared memberships and website
outputs can be regenerated. Stale memberships: run `make prepare`. Missing or
mismatched exports: run `make export` then `make page`. A busy port can be reused
or changed with `PORT`. Never edit a snapshot checksum to bypass a failed restore.

## Editing and checking the dashboard

Edit `web/`, then run `make page` and reload. Data fields and exporter registration
live in `analyze.py`; after changing them, run `make build`. Keep geometry exports
separate from table data and bump public schema versions for incompatible changes.
See the [export contract](docs/research.md#dashboard-export-contract).

Prioritize a clear statewide pattern when developing the map. Minor visual
discrepancies are acceptable; add precision handling only when a discrepancy
changes the meaningful interpretation.

Run `make test` for Python logic changes. Open [tests/browser.html](tests/browser.html)
in a browser for animation and eligibility-display checks: it loads the real
browser scripts, reports pass/fail, and needs no extra runtime. These checks are
manual and are not part of `make test`. Also inspect filters/reset, merged cells,
map navigation, hover values, and narrow layouts when changing their behavior.

Stories are registered in `web/stories.js`, whose `active` ID chooses the published
journey. `web/story-act181.js` preserves the original five chapters with
`enabled: false`; `web/story-overview.js` is the active four-chapter Housing Growth
Area comparison. It shows the four future land use categories within Housing
Growth Areas (prepared blocks), colors municipalities with and without them, shows their
intersection and difference with mapped Tier 1B, then summarizes municipal Tier 1B
coverage. Hovers report one "Submission stage" (each region's selected map stage);
coverage colors do not imply final approval.
Overlap polygons are green and uncovered polygons are red; yellow identifies
municipalities with mixed coverage. Tier 1B has no separate outline layer; green and
red pieces share one hover that gives the piece's acreage within its Housing Growth
Area. Split pieces under one acre are hidden in the browser as display slivers; a
whole area under one acre still shows. Boundary slivers narrower than 4 m join their
largest neighbor during preparation. Shared split boundaries retain detailed
geometry during export so complementary pieces do not develop display seams.
Excluded boundary fragments remain in saved data and audit provenance and are
omitted from the map. Block counts and coverage use analytical geometry only.
“Cannot assess” appears in the legend only when the loaded data contains an
unknown classification; “No Housing Growth Areas” remains a separate category.
Disabled stories are never mounted or reachable
through a URL. To restore the original, set its `enabled` flag to `true`, change
`active` to `act181`, then run `make page`. Only the active story is visible.

Each story's `create` function receives saved map/Tier 1B/housing growth data and the shared
palette, and returns `steps` (copy, count predicates, polygon keys) and `groups`
(one nonempty transition group per chapter interval). Counts select municipalities
unless a step sets `statsOf: 'areas'`, which counts Housing Growth Areas; `statsTitle`
names the key. A count with a `color` shows a map-key swatch; omit `color` when
municipalities are unfilled. An `areaKey` entry of `[color, label, 'outline']` draws
an outline swatch.
Steps marked `municipalFill: true` limit hover to municipalities; other steps
limit hover to area polygons. The hovered polygon's fill darkens slightly; over
category polygons, the whole Housing Growth Area under the pointer is shaded. One shared
hover card follows the pointer; entering controls or leaving the map closes it. Dragging
or zooming clears hover, and polygons ignore hover mid-drag. A drag ends when the
pointer leaves the map or window, so a release outside it is never lost. Leaflet's SVG renderers
draw polygons half a view beyond each edge (`padding: 0.5`), so short drags reveal
no undrawn shapes. For example,
`item.kind === 'tier' ? {opacity: 0.9, fillOpacity: 0.6} : {}` reveals Tier 1B.
Transitions target shared `town`, `area`, and `tier` layers; hidden polygon
interactions follow their sampled opacity, regardless of chapter order.
`overlays` lists the polygon layers a story uses (`area`, `tier`,
`housing-category`, `housing-block`, `housing-coverage`); only those are mounted on
the map while their stroke or fill is visible. Fully transparent polygons stay in
memory but leave the map, avoiding zoom redraws; fades keep both scenes mounted
until their opacity reaches zero. Reverse navigation restores styles, focus, and
layer order. `housing-block` polygons appear only for hover shading and never take hover.
To add a story, register a unique ID in a new `web/story-*.js` file and include it
before `dashboard.js` in `analyze.py`'s script list. New polygon datasets still need
a provenance-validated export and a layer adapter in `dashboard.js`; story files
do not acquire data. Stories require at least two chapters. Scroll distance and
navigation adapt to the chapter count. No public story picker is shown.

Chapter copy, groups, and counts live in the story files; scroll timeline sampling
lives in `web/story-animation.js`; display-only criteria logic lives in
`web/eligibility-display.js`. Colors and layout live in `web/dashboard.css`.
The logo at `web/assets/lbh-logo.svg` was downloaded unmodified on September 12,
2026 from the [Let's Build Homes reports site](https://reports.letsbuildhomes.org/static/img/lbh-landscape-rgb-2.svg)
and is embedded for offline use. Leaflet retains its upstream license notices.

The Focus pill selects Vermont or one of the 11 saved RPC
regions. A regional focus fits that boundary and fades other regions' overlays
and hover targets out throughout the story; the basemap stays visible everywhere.
Panning and chapter changes retain focus. Selecting a region or Vermont refits the
map; × clears the filter without moving the map. The target button on the pill's
left refits the current focus. Target changes use a direct pan/zoom transition
with the padded destination computed at the final zoom, avoiding a flight arc
(native 250ms eased zooms, 450ms pans, and 350ms overlay fades; immediate with
reduced motion); initial layout and resizing remain immediate. Story counts follow the focus; the data table keeps
its own filters.
Native movement retains basemap tile levels throughout zooming; tile fade-in is
disabled. Focus opacity transitions apply only to vector overlays.

On viewports at least 1000px wide and 700px tall, the map fills a sticky viewport
while native page scrolling selects the active story's chapters with 125vh between chapters
and no final scroll hold. Map styles and card positions are sampled directly from scroll position;
there is no timed playback to catch up after fast scrolling. Cards move over each
entire interval on a smoothstep ease-in/ease-out curve, leaving upward and entering
from below without stationary segments. Map overlays
transition from 50% to 100%. Both arrive at the next dot together.
Desktop fitting uses the map zone's actual bounds, with 32px outer margins and
space reserved for Focus at its top center, with a downward-opening menu. The
horizontal −/+ zoom pill sits beside Focus in a centered group with a 16px gap;
both pills are 38px tall. Zoom changes by half a level. Trackpad pinches zoom the map rather than the page;
plain wheel scrolling still advances the story. Desktop pinches batch input into one
transform per animation frame, preserving the point beneath the cursor. Geometry is
redrawn and zoom snaps to a quarter level only when the gesture ends. This uses the
vendored Leaflet touch-zoom internals; check browser regressions when upgrading Leaflet.
Touchscreen pinches use Leaflet's
native touch zoom; custom Safari gesture handling is reserved for devices without
touch points so it does not compete with native pinching on iPhone/iPad.
The vertical timeline occupies a separate right-hand strip beyond the cards;
cards and timeline share the same vertical center at each step. A dot grows only
once reached, and shrinks halfway into the next interval as its overlay leg starts.
Skip to data remains centered at the bottom. Compact layouts retain horizontal
navigation.
Back/Next and dots move the page with a 1050ms ease-in/ease-out scroll; wheel,
touch, pointer, or keyboard input cancels it. Smaller windows place the compact
timeline between the map and card text on one background, without a skip link.
In that compact layout, navigation animates map styles over 1275ms with the same
ease-in/ease-out in either direction. The progress line and dots follow the map's
rendered playhead while the card stays stationary; rapid clicks retarget from
the current map state.
Reduced motion swaps complete scenes immediately without card movement.
The navigation track fills as the story advances and ends at the final chapter;
its dots select chapters and arrows move between chapters. On desktop, the track
is vertical beside the cards, and the centered bottom skip link leads to the
table. Focus, recenter, and zoom controls form a group at the top center of the
map zone. Compact layouts place that group above the horizontal timeline.
Check forward and reverse scrolling, direct navigation, resizing, and the final
release into the table when changing this behavior.
