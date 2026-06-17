UV = uv run python3

.PHONY: all extract transform analyze clean rebuild serve

all: extract transform analyze status

extract:
	$(UV) extract.py

transform:
	$(UV) transform.py

analyze:
	$(UV) analyze.py

status:
	$(UV) status.py

clean:
	rm -rf in/* data/* out/*

rebuild: clean all

serve:
	python3 -m http.server 8000 -d out
