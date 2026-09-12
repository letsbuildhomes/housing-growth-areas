UV = uv run python3

.DEFAULT_GOAL := build
.PHONY: all build export ingest extract transform analyze status clean rebuild serve legacy legacy-status test

all: build

# Website work is entirely local: these targets never download or ingest data.
build: export
	$(UV) build_dashboard.py

export:
	$(UV) export_data.py

ingest: extract

# The original overlay analysis reads the original in/*.geojson cache.
legacy: transform analyze legacy-status

legacy-status:
	$(UV) legacy_status.py

test:
	$(UV) -m unittest discover -v

extract:
	$(UV) extract.py

transform:
	$(UV) transform.py

analyze:
	$(UV) analyze.py

status:
	$(UV) status.py

clean:
	rm -rf out/dashboard

rebuild:
	$(MAKE) clean
	$(MAKE) build

serve: build
	python3 -m http.server 8000 --bind 127.0.0.1 -d out/dashboard
