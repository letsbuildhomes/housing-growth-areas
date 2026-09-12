"""Discover map layers at each refresh, retaining the viewer's filters and context."""
import hashlib
import re

from arcgis import fetch_json

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
