"""Build a standalone HTML page from static exports. Never opens the database."""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'out' / 'dashboard'


def build(output=OUTPUT):
    output = Path(output)
    dataset = json.loads((output / 'data' / 'interim-areas.json').read_text())
    map_dataset = json.loads((output / 'data' / 'map.json').read_text())
    if dataset['schema_version'] != 1:
        raise ValueError('Unsupported interim export schema')
    if map_dataset['schema_version'] != 2:
        raise ValueError('Unsupported map export schema')
    # Embedded JSON lets the page work directly via file:// as well as a static
    # server. Escape HTML delimiters so source strings cannot close the script.
    payload = json.dumps(dataset, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    substitutions = {
        '{{LOGO}}': 'data:image/svg+xml;base64,' + base64.b64encode((ROOT / 'web' / 'assets' / 'lbh-logo.svg').read_bytes()).decode('ascii'),
        '{{STYLES}}': (ROOT / 'web' / 'dashboard.css').read_text(),
        '{{LEAFLET_CSS}}': (ROOT / 'web' / 'vendor' / 'leaflet.css').read_text(),
        '{{LEAFLET_JS}}': (ROOT / 'web' / 'vendor' / 'leaflet.js').read_text(),
        '{{SCRIPT}}': '\n'.join((ROOT / 'web' / name).read_text() for name in
                               ('story-animation.js', 'eligibility-display.js', 'dashboard.js')),
        '{{DATA}}': payload,
        '{{MAP_DATA}}': json.dumps(map_dataset, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e'),
    }
    html = (ROOT / 'web' / 'index.html').read_text()
    for marker, value in substitutions.items():
        if html.count(marker) != 1:
            raise ValueError(f'Expected exactly one template marker: {marker}')
        html = html.replace(marker, value)
    target = output / 'index.html'
    temp = target.with_suffix('.html.tmp')
    temp.write_text(html)
    temp.replace(target)
    print(f'Built {target} (embedded data and assets; online street basemap)')


if __name__ == '__main__':
    build()
