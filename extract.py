import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config


def fetch_json(url, params, retries=3):
    body = urlencode(params, doseq=False).encode("utf-8")
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(url, data=body, headers={
                "Content-Type": "application/x-www-form-urlencoded",
            })
            with urlopen(request, timeout=120) as response:
                return json.load(response)
        except Exception as exc:
            last_error = exc
            time.sleep(1 + attempt)
    raise last_error


def get_layer_meta(layer_url):
    try:
        req = Request(layer_url + "?f=json")
        with urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except Exception as exc:
        print(f"  WARN could not fetch layer metadata: {exc}")
        return None


def download_layer(source_key, source_cfg):
    url = source_cfg["url"]
    out_path = config.IN_DIR / f"{source_key}.geojson"
    meta_path = config.IN_DIR / f"{source_key}_meta.json"

    print(f"  [{source_key}] downloading from {url}")

    meta = get_layer_meta(url)
    if meta:
        meta_path.write_text(json.dumps(meta, separators=(",", ":")))
    else:
        print(f"  [{source_key}] no metadata saved")

    object_id_field = "OBJECTID"
    if meta and meta.get("objectIdField"):
        object_id_field = meta["objectIdField"]
    elif meta and meta.get("fields"):
        for f in meta["fields"]:
            if f.get("type") == "esriFieldTypeOID":
                object_id_field = f["name"]
                break

    count_params = {
        "f": "json",
        "where": "1=1",
        "returnCountOnly": "true",
    }
    count_data = fetch_json(url + "/query", count_params)
    total = count_data.get("count", 0)
    print(f"  [{source_key}] {total} features expected")

    max_batch = 2000
    features = []
    offset = 0

    while True:
        params = {
            "f": "geojson",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": "4326",
            "geometryPrecision": "6",
            "resultOffset": str(offset),
            "resultRecordCount": str(max_batch),
        }
        data = fetch_json(url + "/query", params)
        if "error" in data:
            raise RuntimeError(f"ArcGIS error at offset {offset}: {data['error']}")
        batch = data.get("features", [])
        if not batch:
            break
        features.extend(batch)
        offset += len(batch)
        print(f"  [{source_key}] ... {offset} / {total}", end="\r")
        if offset >= total:
            break

    print(f"\n  [{source_key}] collected {len(features)} features")

    output = {"type": "FeatureCollection", "features": features}
    out_path.write_text(json.dumps(output, separators=(",", ":")))
    print(f"  [{source_key}] wrote {out_path}")
    return len(features)


def main():
    config.IN_DIR.mkdir(parents=True, exist_ok=True)
    success = []
    skipped = []
    failed = []

    for source_key, source_cfg in config.SOURCES.items():
        out_path = config.IN_DIR / f"{source_key}.geojson"
        if out_path.exists():
            count = 0
            try:
                with open(out_path) as f:
                    data = json.load(f)
                count = len(data.get("features", []))
            except Exception:
                pass
            skipped.append((source_key, count))
            continue
        try:
            count = download_layer(source_key, source_cfg)
            success.append((source_key, count))
        except Exception as exc:
            print(f"  [{source_key}] FAILED: {exc}")
            failed.append(source_key)

    print()
    print("── extract summary ──")
    if success:
        for k, n in success:
            print(f"  DOWNLOADED {k}: {n} features")
    if skipped:
        for k, n in skipped:
            print(f"  SKIPPED    {k}: {n} features (cached)")
    if failed:
        for k in failed:
            print(f"  FAILED     {k}")
    print(f"  total: {sum(n for _, n in success) + sum(n for _, n in skipped)} features")
    if failed:
        print(f"  {len(failed)} source(s) could not be downloaded")


if __name__ == "__main__":
    main()
