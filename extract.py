"""Discover public ArcGIS layers and capture immutable raw snapshots."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from arcgis import download, fetch_json, object_id_field, query_ids
from config import SNAPSHOT_ROOT


# Source definitions and discovery

PORTAL = 'https://www.arcgis.com/sharing/rest/content/items/'
EXPERIENCES = {
    'flu': '58543fd6882d4bd6bd0b3008d98e874e',
    'interim': 'd96022b7dce64945a326e7bf98a2f365',
}
# Published by the same state organization, but absent from the viewer's
# approved group at discovery (2026-09-08). Resolve its URL through the item.
APPROVED_FLU_ITEM = 'bf09ba3367404b88933b55f31726ab81'
BOUNDARY_ITEMS = {
    'municipality_boundary': '3f464b0e1980450e9026430a635bff0a',
    'rpc_boundary': 'b311ad21d306477eb2bbefa95fe6460d',
}
RPC_LABELS = {
    'Windham RC': 'WR', 'Two Rivers-Ottauquechee RC': 'TR',
    'Rutland Regional PC': 'RR', 'Northwest RPC': 'NW',
    'Northeastern Vermont Development Assoc.': 'NV', 'Mount Ascutney RC': 'MA',
    'Lamoille County PC': 'LC', 'Central Vermont RPC': 'CV',
    'Chittenden County RPC': 'CC', 'Bennington County RC': 'BC',
    'Addison County RPC': 'AC',
}
INTERIM_KINDS = {
    'I.)': 'downtown_district', 'II.)': 'town_growth_development',
    'III.)': 'village_center_buffer',
}


def source_id(url):
    return hashlib.sha256(url.rstrip('/').encode()).hexdigest()[:16]


def walk(layers, parents=()):
    for layer in layers:
        path = parents + (layer.get('title', ''),)
        yield path, layer
        yield from walk(layer.get('layers', []), path)


def select_layer(map_name, path, layer):
    if not layer.get('url'):
        return None
    title = path[-1]
    if map_name == 'interim':
        kind = next((v for k, v in INTERIM_KINDS.items() if title.startswith(k)), None)
        if not kind or len(path) != 1:
            return None
        return dict(kind='interim', category=kind, stage='interim', rpc=None)
    if not path[0].startswith(('Under Review:', 'Approved:')):
        return None
    if title == 'FLU Areas' or ('Approved' in title and 'Land Use' in title):
        kind = 'flu'
    elif title in ('Tier 1B', 'Tier 1A Areas', 'Approved Act 250 Tier Areas'):
        kind = 'tier'
    elif title.lower() in ('hamlet', 'hamlets'):
        kind = 'hamlet'
    else:
        return None
    stage = ('approved' if path[0].startswith('Approved:') else
             'pre_application' if 'Pre-application' in path else
             'application' if 'Application' in path else 'under_review')
    return dict(kind=kind, category=kind, stage=stage,
                rpc=next((RPC_LABELS[p] for p in path if p in RPC_LABELS), None))


def discover():
    documents, layers = {}, []
    for name, item_id in EXPERIENCES.items():
        experience = fetch_json(PORTAL + item_id + '/data')
        documents[name + '_experience'] = experience
        maps = [d for d in experience.get('dataSources', {}).values()
                if d.get('type') == 'WEB_MAP']
        if not maps:
            raise RuntimeError(f'No web map found in {name} experience')
        selected = 0
        for data_source in maps:
            map_id = data_source['itemId']
            webmap = fetch_json(PORTAL + map_id + '/data')
            documents[map_id] = webmap
            for path, layer in walk(webmap['operationalLayers']):
                context = select_layer(name, path, layer)
                if context is None:
                    continue
                url = layer['url'].rstrip('/')
                if not re.search(r'/(?:FeatureServer|MapServer)/\d+$', url):
                    raise RuntimeError(f'Expected a queryable leaf layer: {url}')
                layers.append(dict(
                    layer_id=map_id + ':' + layer['id'], source_id=source_id(url),
                    url=url, path=list(path), webmap_id=map_id,
                    where=layer.get('layerDefinition', {}).get('definitionExpression') or '1=1',
                    map_definition=layer, **context,
                ))
                selected += 1
        if selected == 0 or (name == 'interim' and selected != 3):
            raise RuntimeError(f'Unexpected selected layer count for {name}: {selected}')

    item = fetch_json(PORTAL + APPROVED_FLU_ITEM)
    service = fetch_json(item['url'])
    documents['approved_flu_item'] = item
    documents['approved_flu_service'] = service
    for leaf in service['layers']:
        url = item['url'].rstrip('/') + '/' + str(leaf['id'])
        if any(l['url'] == url and l['stage'] == 'approved' for l in layers):
            continue
        layers.append(dict(
            layer_id=APPROVED_FLU_ITEM + ':' + str(leaf['id']), source_id=source_id(url),
            url=url, path=['Approved: FLU & TIER Data', 'Approved Future Land Use Areas'],
            webmap_id=None, where='1=1', map_definition=leaf,
            kind='flu', category='flu', stage='approved', rpc=None,
        ))
    if not any(l['kind'] == 'tier' and l['stage'] == 'approved' for l in layers):
        raise RuntimeError('Approved tier layer is missing from the map')
    if not any(l['kind'] == 'flu' and l['stage'] == 'approved' for l in layers):
        raise RuntimeError('Approved FLU service has no published layers')

    for kind, item_id in BOUNDARY_ITEMS.items():
        item = fetch_json(PORTAL + item_id)
        service_url = item['url'].rstrip('/')
        service = fetch_json(service_url)
        spatial_layers = [leaf for leaf in service.get('layers', [])
                          if leaf.get('geometryType') == 'esriGeometryPolygon']
        if len(spatial_layers) != 1:
            raise RuntimeError(f'Expected one polygon layer for {item["title"]}')
        leaf = spatial_layers[0]
        url = service_url + '/' + str(leaf['id'])
        documents[kind + '_item'] = item
        documents[kind + '_service'] = service
        layers.append(dict(
            layer_id=item_id + ':' + str(leaf['id']), source_id=source_id(url),
            url=url, path=[item['title']], webmap_id=None, where='1=1',
            map_definition=leaf, kind=kind, category=kind,
            stage='reference', rpc=None,
        ))
    return documents, layers


# Raw snapshot capture

def write_json(path, value):
    path.write_text(json.dumps(value, separators=(',', ':'), ensure_ascii=False))


def sha256(path):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def capture(root=SNAPSHOT_ROOT, workers=4):
    started = datetime.now(timezone.utc)
    run_id = started.strftime('%Y%m%dT%H%M%S.%fZ')
    directory = root / run_id
    directory.mkdir(parents=True)
    documents, layers = discover()
    write_json(directory / 'map_documents.json', documents)
    sources = {layer['source_id']: layer['url'] for layer in layers}

    def capture_source(pair):
        sid, url = pair
        meta = fetch_json(url)
        if not meta.get('geometryType'):
            raise RuntimeError(f'Expected spatial layer: {url}')
        collection = download(url, meta)
        oid = object_id_field(meta)
        all_ids = {f['properties'][oid] for f in collection['features']}
        memberships = {}
        for layer in (l for l in layers if l['source_id'] == sid):
            ids = sorted(all_ids) if layer['where'] == '1=1' else query_ids(url, layer['where'])
            if not set(ids).issubset(all_ids):
                raise RuntimeError(f'Map membership changed during capture: {url}')
            memberships[layer['layer_id']] = ids
        if meta.get('editingInfo') != fetch_json(url).get('editingInfo'):
            raise RuntimeError(f'Source edited while capturing map membership: {url}')
        write_json(directory / (sid + '.geojson'), collection)
        write_json(directory / (sid + '_meta.json'), meta)
        print(f"  {meta['name']}: {len(all_ids)} features", flush=True)
        return dict(source_id=sid, url=url, count=len(all_ids), memberships=memberships)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        captured = list(pool.map(capture_source, sources.items()))
    manifest = dict(
        schema_version=1, run_id=run_id, started_at=started.isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(), crs='EPSG:4326',
        layers=layers, sources=captured,
        files={p.name: sha256(p) for p in directory.iterdir() if p.is_file()},
    )
    # No manifest means incomplete capture, never a reusable cache.
    write_json(directory / 'manifest.json', manifest)
    return directory


def main():
    parser = argparse.ArgumentParser(description='Capture raw sources only; does not load DuckDB.')
    parser.add_argument('--output', type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 9))
    args = parser.parse_args()
    print(f'Snapshot: {capture(args.output, args.workers)}')


if __name__ == '__main__':
    main()
