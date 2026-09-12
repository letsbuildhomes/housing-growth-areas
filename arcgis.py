"""Strict, complete ArcGIS downloads; no silent truncation or geometry rounding."""
import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen


def fetch_json(url, params=None, retries=3):
    query = urlencode({'f': 'json', **(params or {})})
    for attempt in range(retries):
        try:
            with urlopen(url + '?' + query, timeout=120) as response:
                result = json.load(response)
            if 'error' in result:
                raise RuntimeError(f"ArcGIS error at {url}: {result['error']}")
            return result
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(attempt + 1)


def object_id_field(meta):
    return meta.get('objectIdField') or next(
        f['name'] for f in meta['fields'] if f['type'] == 'esriFieldTypeOID'
    )


def query_ids(url, where='1=1'):
    result = fetch_json(url + '/query', {
        'where': where, 'returnIdsOnly': 'true',
    })
    if 'objectIds' not in result or result.get('exceededTransferLimit'):
        raise RuntimeError(f'Incomplete object ID response: {url}')
    ids = result['objectIds'] or []
    if len(ids) != len(set(ids)):
        raise RuntimeError(f'Duplicate object IDs: {url}')
    count = fetch_json(url + '/query', {
        'where': where, 'returnCountOnly': 'true',
    })['count']
    if len(ids) != count:
        raise RuntimeError(f'Object IDs/count disagree: {url}: {len(ids)} != {count}')
    return sorted(ids)


def download(url, meta, batch_size=100):
    oid = object_id_field(meta)
    ids = query_ids(url)

    def batch(requested):
        try:
            data = fetch_json(url + '/query', {
                'f': 'geojson', 'objectIds': ','.join(map(str, requested)),
                'outFields': '*', 'returnGeometry': 'true', 'outSR': '4326',
            })
        except (ValueError, json.JSONDecodeError):
            # ArcGIS can return a response truncated at its JSON-size limit
            # before it can report exceededTransferLimit. Split the requested
            # IDs and retry so large geometries still receive completeness
            # checks instead of being silently discarded.
            if len(requested) == 1:
                raise
            middle = len(requested) // 2
            return batch(requested[:middle]) + batch(requested[middle:])
        if data.get('type') != 'FeatureCollection':
            raise RuntimeError(f'Expected GeoJSON FeatureCollection: {url}')
        features = data['features']
        actual = [f['properties'].get(oid) for f in features]
        if (data.get('exceededTransferLimit') or len(actual) != len(requested)
                or set(actual) != set(requested)):
            if len(requested) == 1:
                raise RuntimeError(f'Missing or duplicate feature {requested}: {url}')
            middle = len(requested) // 2
            return batch(requested[:middle]) + batch(requested[middle:])
        return features

    features = []
    size = min(batch_size, meta.get('maxRecordCount') or batch_size)
    for start in range(0, len(ids), size):
        features.extend(batch(ids[start:start + size]))
        if len(features) % 1000 == 0:
            print(f"  {meta.get('name', url)}: downloaded {len(features)}/{len(ids)}", flush=True)
    if ids != query_ids(url):
        raise RuntimeError(f'Source IDs changed during download; rerun: {url}')
    after = fetch_json(url)
    if meta.get('editingInfo') != after.get('editingInfo'):
        raise RuntimeError(f'Source edited during download; rerun: {url}')
    return {'type': 'FeatureCollection', 'features': features}
