import html
import json
import sqlite3
from pathlib import Path

from shapely import from_wkb, to_wkb
from shapely.geometry import GeometryCollection, MultiPolygon, mapping
from shapely.ops import unary_union
from shapely.validation import make_valid

import config


def load_geometries(conn, table, column, values):
    placeholders = ", ".join("?" for _ in values)
    query = f"SELECT geometry, rpc, version FROM {table} WHERE {column} IN ({placeholders})"
    rows = conn.execute(query, list(values)).fetchall()
    results = []
    for geom_wkb, rpc, version in rows:
        if not geom_wkb:
            continue
        try:
            geom = from_wkb(bytes.fromhex(geom_wkb))
            if geom is None or geom.is_empty:
                continue
            if geom.geom_type not in ("Polygon", "MultiPolygon"):
                geom = polygonal_only(geom)
            if geom.is_empty:
                continue
            results.append((make_valid(geom), rpc, version))
        except Exception:
            continue
    return results


def polygonal_only(geom):
    if geom.is_empty:
        return geom
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    if isinstance(geom, GeometryCollection):
        polys = [
            part for part in geom.geoms
            if part.geom_type in ("Polygon", "MultiPolygon") and not part.is_empty
        ]
        if not polys:
            return MultiPolygon([])
        return unary_union(polys)
    return MultiPolygon([])


def union_all(geoms):
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return MultiPolygon([])
    result = unary_union(geoms)
    return polygonal_only(result)


def sq_miles(geom):
    geom = polygonal_only(geom)
    if geom.is_empty:
        return 0.0
    area, _ = config.GEOD.geometry_area_perimeter(geom)
    return abs(area) / config.SQ_M_PER_SQ_MI


def make_feature(class_id, label, color, geom, notes):
    geom = polygonal_only(geom)
    return {
        "type": "Feature",
        "geometry": mapping(geom),
        "properties": {
            "class_id": class_id,
            "label": label,
            "color": color,
            "notes": notes,
        },
    }


def build_overlay(conn):
    growth_geoms = load_geometries(conn, "flu_areas", "flu_code", list(config.GROWTH_CODES))
    tier_geoms = load_geometries(conn, "tier_areas", "tier_code", ["1B"])

    growth_union = union_all([g for g, *_ in growth_geoms])
    all_tier = union_all([g for g, *_ in tier_geoms])

    pre_tier = union_all([g for g, r, v in tier_geoms if v == "PRE"])
    app_tier = union_all([g for g, r, v in tier_geoms if v == "APP"])
    any_tier = union_all([g for g, r, v in tier_geoms])

    app_overlap = growth_union.intersection(app_tier)
    pre_overlap = growth_union.intersection(pre_tier).difference(app_tier)
    no_tier = growth_union.difference(any_tier)

    total_growth_sq_mi = sq_miles(growth_union)
    tier1b_growth_sq_mi = sq_miles(any_tier)
    tier1b_growth_pct = (tier1b_growth_sq_mi / total_growth_sq_mi * 100) if total_growth_sq_mi else 0.0

    growth_counts = {}
    for row in conn.execute("SELECT flu_code, COUNT(*) FROM flu_areas WHERE flu_code IN ("
                             + ",".join("?" for _ in config.GROWTH_CODES)
                             + ") GROUP BY flu_code", list(config.GROWTH_CODES)):
        growth_counts[row[0]] = row[1]

    tier_counts = {}
    for row in conn.execute("SELECT version, COUNT(*) FROM tier_areas WHERE tier_code='1B' GROUP BY version"):
        tier_counts[row[0] or "OTHER"] = row[1]

    fc = {
        "type": "FeatureCollection",
        "name": "Act 181 Growth Areas by Tier 1B Status",
        "features": [
            make_feature(
                "growth_no_tier1b",
                "Growth Area but no Tier 1B",
                "#d73027",
                no_tier,
                "Growth categories DC, VC, VA, and PGA minus all Tier 1B geometry, including blank-version Tier 1B records.",
            ),
            make_feature(
                "growth_pre_tier1b",
                "Growth Area with pre-application Tier 1B",
                "#2f80ed",
                pre_overlap,
                "Growth categories intersected with Tier 1B records where version is PRE.",
            ),
            make_feature(
                "growth_app_tier1b",
                "Growth Area with final application Tier 1B",
                "#1f8a4c",
                app_overlap,
                "Growth categories intersected with Tier 1B records where version is APP.",
            ),
        ],
        "metadata": {
            "growth_codes": config.GROWTH_CODES,
            "growth_feature_counts": growth_counts,
            "tier_feature_counts": tier_counts,
            "area_stats": {
                "total_growth_sq_mi": round(total_growth_sq_mi, 2),
                "growth_with_any_tier1b_sq_mi": round(tier1b_growth_sq_mi, 2),
                "growth_with_any_tier1b_pct": round(tier1b_growth_pct, 2),
            },
            "processing_note": "Boolean overlay computed in WGS84 coordinates for map visualization.",
        },
    }

    return fc


def write_overlay(fc, path):
    path.write_text(json.dumps(fc, separators=(",", ":")))
    print(f"wrote {path}")
    meta = fc.get("metadata", {})
    print(json.dumps(meta.get("area_stats", {}), indent=2))


LEAFLET_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vermont Act 181 Growth Areas and Tier 1B</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    :root {
      --ink: #1f2933;
      --muted: #5e6b78;
      --line: #d7dde3;
      --panel: #ffffff;
      --accent: #16775c;
      --accent-dark: #0e4f40;
      --growth-only: #d73027;
      --pre: #2f80ed;
      --app: #1f8a4c;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); }
    body { overflow: hidden; }
    #app { height: 100%; display: grid; grid-template-rows: auto 1fr; background: #eef2f1; }
    header {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 16px;
      align-items: center;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      z-index: 500;
    }
    h1 { margin: 0; font-size: 18px; line-height: 1.2; font-weight: 680; }
    .sub { margin-top: 3px; color: var(--muted); font-size: 13px; }
    .stats { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    .stat { min-width: 148px; padding: 7px 9px; border: 1px solid var(--line); border-radius: 6px; background: #f7f9fa; }
    .stat-value { display: block; font-size: 17px; line-height: 1.1; font-weight: 720; }
    .stat-label { display: block; margin-top: 2px; color: var(--muted); font-size: 11px; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: flex-end; }
    button { height: 34px; border: 1px solid var(--line); background: #fff; color: var(--ink); font: inherit; font-size: 13px; border-radius: 6px; padding: 0 11px; cursor: pointer; }
    button:hover { border-color: var(--accent); color: var(--accent-dark); }
    #map { min-height: 0; height: 100%; width: 100%; }
    .leaflet-popup-content { margin: 10px 12px; min-width: 220px; }
    .popup-title { font-weight: 700; margin-bottom: 6px; }
    .popup-grid { display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 4px 10px; font-size: 13px; }
    .popup-grid span:nth-child(odd) { color: var(--muted); }
    .info { padding: 9px 10px; background: rgba(255,255,255,0.96); border: 1px solid var(--line); border-radius: 6px; box-shadow: 0 1px 8px rgba(20,30,40,0.12); font-size: 13px; min-width: 170px; margin-top: 1em; }
    .info strong { display: block; margin-bottom: 4px; font-size: 14px; }
    .legend-row { display: flex; align-items: center; gap: 7px; margin-top: 5px; }
    .swatch { width: 13px; height: 13px; border-radius: 3px; border: 1px solid rgba(0,0,0,0.25); }
    @media (max-width: 760px) {
      header { grid-template-columns: 1fr; gap: 10px; }
      .toolbar { justify-content: flex-start; }
    }
    .leaflet-control-layers{margin-top:1em!important}
  </style>
</head>
<body>
  <div id="app">
    <header>
      <div>
        <h1>Act 181 Growth Areas and Tier 1B</h1>
        <div class="sub">FLU growth categories DC, VC, VA, and PGA classified by Tier 1B overlap</div>
        <div class="stats">
          <div class="stat"><span class="stat-value" id="stat-total-growth">--</span><span class="stat-label">sq mi growth areas</span></div>
          <div class="stat"><span class="stat-value" id="stat-tier-growth">--</span><span class="stat-label">sq mi growth area + any Tier 1B</span></div>
          <div class="stat"><span class="stat-value" id="stat-tier-pct">--</span><span class="stat-label">growth area land mass with Tier 1B</span></div>
        </div>
      </div>
      <div class="toolbar">
        <button type="button" id="fit">Fit</button>
      </div>
    </header>
    <main id="map"></main>
  </div>
  <script id="overlay-data" type="application/json">__GEOJSON__</script>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const data = JSON.parse(document.getElementById("overlay-data").textContent);
    const map = L.map("map", { zoomControl: true }).setView([44.05, -72.7], 8);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    const colors = {
      growth_no_tier1b: getComputedStyle(document.documentElement).getPropertyValue("--growth-only").trim(),
      growth_pre_tier1b: getComputedStyle(document.documentElement).getPropertyValue("--pre").trim(),
      growth_app_tier1b: getComputedStyle(document.documentElement).getPropertyValue("--app").trim()
    };

    function fmtNumber(v, d) {
      return Number(v).toLocaleString(undefined, {maximumFractionDigits:d, minimumFractionDigits:d});
    }

    function esc(s) {
      return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
    }

    const classMeta = [
      { id: "growth_app_tier1b", label: "Growth with final-app Tier 1B" },
      { id: "growth_pre_tier1b", label: "Growth with pre-app Tier 1B" },
      { id: "growth_no_tier1b", label: "Growth Area, no Tier 1B" },
    ];

    const overlayLayers = {};
    let allBounds;

    classMeta.forEach(m => {
      const features = data.features.filter(f => f.properties && f.properties.class_id === m.id && f.geometry);
      if (features.length === 0) return;
      const layer = L.geoJSON(features, {
        style: { color: colors[m.id], weight: 1.2, opacity: 0.95, fillColor: colors[m.id], fillOpacity: 0.46 },
        onEachFeature(f, fl) {
          const p = f.properties || {};
          fl.bindPopup('<div class="popup-title">' + esc(p.label||"") + '</div><div class="popup-grid"><span>Notes</span><span>' + esc(p.notes||"") + '</span><span>Class</span><span>' + esc(p.class_id||"") + '</span></div>');
          fl.on({
            mouseover(e) { e.target.setStyle({weight:3,fillOpacity:0.52}); e.target.bringToFront(); },
            mouseout(e) { layer.resetStyle(e.target); }
          });
        }
      });
      overlayLayers[m.label] = layer;
      if (!allBounds) allBounds = layer.getBounds();
      else allBounds.extend(layer.getBounds());
    });

    Object.values(overlayLayers).forEach(l => l.addTo(map));

    const legend = L.control({ position: "topright" });
    legend.onAdd = () => {
      const d = L.DomUtil.create("div", "info");
      d.innerHTML = '<strong>Growth Area Status</strong>'
        + '<div class="legend-row"><span class="swatch" style="background:'+colors.growth_no_tier1b+'"></span><span>Growth Area but no Tier 1B</span></div>'
        + '<div class="legend-row"><span class="swatch" style="background:'+colors.growth_pre_tier1b+'"></span><span>Growth Area with pre-application Tier 1B</span></div>'
        + '<div class="legend-row"><span class="swatch" style="background:'+colors.growth_app_tier1b+'"></span><span>Growth Area with final application Tier 1B</span></div>';
      return d;
    };
    legend.addTo(map);

    if (Object.keys(overlayLayers).length > 1) {
      L.control.layers(null, overlayLayers, { position: "topright" }).addTo(map);
    }

    document.getElementById("fit").addEventListener("click", () => {
      if (allBounds && allBounds.isValid()) map.fitBounds(allBounds, {padding:[18,18]});
    });

    const s = (data.metadata||{}).area_stats||{};
    document.getElementById("stat-total-growth").textContent = fmtNumber(s.total_growth_sq_mi, 1);
    document.getElementById("stat-tier-growth").textContent = fmtNumber(s.growth_with_any_tier1b_sq_mi, 1);
    document.getElementById("stat-tier-pct").textContent = fmtNumber(s.growth_with_any_tier1b_pct, 1) + "%";
    if (allBounds && allBounds.isValid()) map.fitBounds(allBounds, {padding:[18,18]});
  </script>
</body>
</html>
"""


def write_leaflet(geojson_path, html_path):
    geojson = geojson_path.read_text()
    geojson = geojson.replace("</script", "<\\/script")
    html_path.write_text(LEAFLET_TEMPLATE.replace("__GEOJSON__", geojson))
    print(f"wrote {html_path}")


def main():
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH))

    overlay = build_overlay(conn)
    conn.close()

    overlay_path = config.OUT_DIR / "growth_tier_overlay.geojson"
    html_path = config.OUT_DIR / "index.html"

    write_overlay(overlay, overlay_path)
    write_leaflet(overlay_path, html_path)
    print("Done")


if __name__ == "__main__":
    main()
