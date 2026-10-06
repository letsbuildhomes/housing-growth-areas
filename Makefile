UV = uv run python3
PORT ?= 18000
HOST ?= 0.0.0.0
WORKERS ?= 4
SNAPSHOT ?=
VIBES_PROJECT := housing-growth-areas

.DEFAULT_GOAL := build
.DELETE_ON_ERROR:
.PHONY: all build export prepare ingest extract transform analyze page status clean rebuild serve deploy test help setup-spatial

all: build

# Ordinary builds only read the saved database; preparation writes a sidecar.
build: export
	$(MAKE) page

DEPENDENCIES = pyproject.toml uv.lock Makefile
PREPARED = data/municipality-memberships.json data/tier1b-municipal.json data/housing-growth.json
EXPORTS = out/dashboard/data/manifest.json out/dashboard/data/interim-areas.json out/dashboard/data/map.json out/dashboard/data/tier1b.json out/dashboard/data/housing-growth.json

export: $(EXPORTS)

prepare: $(PREPARED)

$(PREPARED) &: data/act181_ingest.duckdb transform.py config.py arcgis.py $(DEPENDENCIES)
	$(UV) transform.py --prepare --force
	@touch $(PREPARED)

# A standalone page rebuild consumes existing exports only.
ifneq ($(strip $(filter all build export analyze serve deploy rebuild $(EXPORTS),$(MAKECMDGOALS))),)
GENERATE_EXPORTS = yes
endif
ifeq ($(MAKECMDGOALS),)
GENERATE_EXPORTS = yes
endif
ifeq ($(GENERATE_EXPORTS),yes)
$(EXPORTS) &: $(PREPARED) data/act181_ingest.duckdb analyze.py transform.py config.py arcgis.py $(DEPENDENCIES)
	$(UV) analyze.py --export
endif

analyze: build

page: out/dashboard/index.html

PAGE_INPUTS = analyze.py config.py $(DEPENDENCIES) $(wildcard web/*.html web/*.css web/*.js web/assets/* web/vendor/*)
out/dashboard/index.html: $(PAGE_INPUTS) $(EXPORTS)
	$(UV) analyze.py --page

# Missing exports are an error, never an implicit fetch or database load.
out/dashboard/data/%.json:
	@test -f "$@" || { echo 'Missing exports. Run make export or make build.' >&2; exit 1; }

# Explicit network operations, never prerequisites of local build targets.
extract:
	$(UV) extract.py --workers $(WORKERS)

ingest:
	$(UV) -c "from extract import capture; from transform import load_snapshot, prepare, prepare_tier, prepare_housing_growth; load_snapshot(capture(workers=$(WORKERS))); prepare(); prepare_tier(); prepare_housing_growth()"

# Pass a completed capture explicitly; never guess which snapshot to restore.
transform:
	@test -n "$(SNAPSHOT)" || { echo 'Usage: make transform SNAPSHOT=in/snapshots/<capture>' >&2; exit 1; }
	$(UV) transform.py --snapshot "$(SNAPSHOT)"

status:
	$(UV) analyze.py --status

test:
	$(UV) -m unittest discover -s tests -v

setup-spatial:
	$(UV) -c "import duckdb; duckdb.connect().execute('INSTALL spatial')"

clean:
	rm -rf out/dashboard

rebuild:
	$(MAKE) clean
	$(MAKE) build

serve: build
	$(UV) -m http.server $(PORT) --bind $(HOST) -d out/dashboard

deploy:
	@: "$${VIBES_DEPLOY_HOST:?Set VIBES_DEPLOY_HOST to user@server or an SSH alias}"
	@printf '%s\n' "$(VIBES_PROJECT)" | LC_ALL=C grep -Eq '^[a-z0-9][a-z0-9-]*$$' || { echo 'Invalid VIBES_PROJECT' >&2; exit 1; }
	$(MAKE) build
	ssh -o BatchMode=yes "$$VIBES_DEPLOY_HOST" 'mkdir -p /srv/http/vibes/$(VIBES_PROJECT)'
	rsync -az --delete --chmod=D755,F644 -e 'ssh -o BatchMode=yes' out/dashboard/ "$${VIBES_DEPLOY_HOST}:/srv/http/vibes/$(VIBES_PROJECT)/"
	ssh -o BatchMode=yes "$$VIBES_DEPLOY_HOST" 'touch -m -- /srv/http/vibes/$(VIBES_PROJECT)'
	@echo 'Published'

help:
	@echo 'Local: make/build, export, prepare, analyze, page, status, test'
	@echo 'Preview: make serve [PORT=8001] [HOST=127.0.0.1]'
	@echo 'Deploy: make deploy (requires VIBES_DEPLOY_HOST; publishes dashboard to vibes)'
	@echo 'Restore: make transform SNAPSHOT=in/snapshots/<capture> (no downloads)'
	@echo 'Network: make extract (capture only), ingest (capture + load), setup-spatial'
	@echo 'Cleanup: make clean/rebuild (dashboard output only; preserves research data)'
	@echo 'Tests: make test (Python); open tests/browser.html for browser checks'
