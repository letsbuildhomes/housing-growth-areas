import json

import duckdb

import config


def polygon_geodesic_area(coords):
    ring = coords[0]
    area, _ = config.GEOD.polygon_area_perimeter(
        [p[0] for p in ring], [p[1] for p in ring]
    )
    area = abs(area)
    for hole in coords[1:]:
        harea, _ = config.GEOD.polygon_area_perimeter(
            [p[0] for p in hole], [p[1] for p in hole]
        )
        area -= abs(harea)
    return area


def geodesic_sq_miles(geom_dict):
    if geom_dict is None:
        return 0.0
    typ = geom_dict.get("type")
    total_m2 = 0.0
    if typ == "Polygon":
        coords = geom_dict.get("coordinates", [])
        if coords and coords[0]:
            total_m2 = polygon_geodesic_area(coords)
    elif typ == "MultiPolygon":
        for poly in geom_dict.get("coordinates", []):
            if poly and poly[0]:
                total_m2 += polygon_geodesic_area(poly)
    elif typ == "GeometryCollection":
        for g in geom_dict.get("geometries", []):
            total_m2 += geodesic_sq_miles(g) * config.SQ_M_PER_SQ_MI
    return total_m2 / config.SQ_M_PER_SQ_MI


def build_overlay(duck):
    rows = duck.execute("""
        SELECT rpc, ST_AsGeoJSON(growth_geom), ST_AsGeoJSON(app_overlap_geom),
               ST_AsGeoJSON(pre_overlap_geom), ST_AsGeoJSON(no_tier_geom)
        FROM overlay_results
    """).fetchall()

    features = []
    total_growth_sq_mi = 0.0
    tier1b_growth_sq_mi = 0.0

    for row in rows:
        rpc_code, growth_json, app_json, pre_json, no_tier_json = row

        growth_dict = json.loads(growth_json) if growth_json else None
        app_dict = json.loads(app_json) if app_json else None
        pre_dict = json.loads(pre_json) if pre_json else None
        no_tier_dict = json.loads(no_tier_json) if no_tier_json else None

        g_sq = geodesic_sq_miles(growth_dict)
        total_growth_sq_mi += g_sq

        app_label = f"{config.RPC_CODES.get(rpc_code, rpc_code)}: final-app Tier 1B"
        pre_label = f"{config.RPC_CODES.get(rpc_code, rpc_code)}: pre-app Tier 1B"
        no_label = f"{config.RPC_CODES.get(rpc_code, rpc_code)}: outside any Tier 1B"

        for is_tier, class_id, label, color, geom_dict, note in [
            (True, "growth_app_tier1b", "Growth with final-app Tier 1B", "#1f8a4c",
             app_dict, app_label),
            (True, "growth_pre_tier1b", "Growth with pre-app Tier 1B", "#2f80ed",
             pre_dict, pre_label),
            (False, "growth_no_tier1b", "Growth Area, no Tier 1B", "#d73027",
             no_tier_dict, no_label),
        ]:
            if geom_dict is None:
                continue
            if geom_dict.get("type") == "GeometryCollection":
                if not geom_dict.get("geometries"):
                    continue
            else:
                coords = geom_dict.get("coordinates", [])
                if not coords or coords == [[]]:
                    continue
            if is_tier:
                tier1b_growth_sq_mi += geodesic_sq_miles(geom_dict)

            features.append({
                "type": "Feature",
                "geometry": geom_dict,
                "properties": {
                    "class_id": class_id,
                    "label": f"{label} — {config.RPC_CODES.get(rpc_code, rpc_code)}",
                    "color": color,
                    "notes": note,
                    "rpc": rpc_code,
                },
            })

    tier1b_growth_pct = (tier1b_growth_sq_mi / total_growth_sq_mi * 100) if total_growth_sq_mi else 0.0

    growth_counts = {}
    for row in duck.execute(
        "SELECT flu_code, COUNT(*) FROM flu_areas WHERE flu_code IN ("
        + ",".join("?" for _ in config.GROWTH_CODES)
        + ") GROUP BY flu_code", list(config.GROWTH_CODES)
    ).fetchall():
        growth_counts[row[0]] = row[1]

    tier_counts = {}
    for row in duck.execute(
        "SELECT version, COUNT(*) FROM tier_areas WHERE tier_code = '1B' GROUP BY version"
    ).fetchall():
        tier_counts[row[0] or "OTHER"] = row[1]

    fc = {
        "type": "FeatureCollection",
        "name": "Act 181 Growth Areas by Tier 1B Status",
        "features": features,
        "metadata": {
            "growth_codes": config.GROWTH_CODES,
            "growth_feature_counts": growth_counts,
            "tier_feature_counts": tier_counts,
            "area_stats": {
                "total_growth_sq_mi": round(total_growth_sq_mi, 2),
                "growth_with_any_tier1b_sq_mi": round(tier1b_growth_sq_mi, 2),
                "growth_with_any_tier1b_pct": round(tier1b_growth_pct, 2),
            },
            "processing_note": "Per-RPC overlay computed in WGS84 coordinates for map visualization.",
        },
    }
    return fc


def load_boundary_layer(duck, boundary_type, label, style):
    rows = duck.execute("""
        SELECT name, geoid, source_layer, ST_AsGeoJSON(ST_Force2D(geom)) AS geojson
        FROM boundary_areas
        WHERE boundary_type = ?
    """, [boundary_type]).fetchall()

    features = []
    for name, geoid, source_layer, geojson_str in rows:
        if not geojson_str:
            continue
        features.append({
            "type": "Feature",
            "geometry": json.loads(geojson_str),
            "properties": {
                "name": name or "",
                "geoid": geoid or "",
                "label": label,
                "source_layer": source_layer or "",
            },
        })

    return {
        "type": "FeatureCollection",
        "label": label,
        "style": style,
        "features": features,
    }


def build_rpc_stats(duck):
    rows = duck.execute("""
        SELECT name, rpc_code,
               ST_AsGeoJSON(rpc_geom), ST_AsGeoJSON(growth_geom),
               ST_AsGeoJSON(pre_geom), ST_AsGeoJSON(app_geom),
               ST_AsGeoJSON(rpc_water_geom), ST_AsGeoJSON(growth_water_geom),
               ST_AsGeoJSON(pre_water_geom), ST_AsGeoJSON(app_water_geom)
        FROM rpc_stats_data
    """).fetchall()

    has_growth = {r[0] for r in duck.execute(
        "SELECT DISTINCT rpc FROM flu_areas WHERE flu_code IN ('DC','VC','VA','PGA') AND rpc IS NOT NULL AND rpc != ''"
    ).fetchall()}
    has_pre = {r[0] for r in duck.execute(
        "SELECT DISTINCT rpc FROM tier_areas WHERE tier_code = '1B' AND version = 'PRE'"
    ).fetchall()}
    has_app = {r[0] for r in duck.execute(
        "SELECT DISTINCT rpc FROM tier_areas WHERE tier_code = '1B' AND version = 'APP'"
    ).fetchall()}

    results = []
    sums = [0.0, 0.0, 0.0, 0.0]

    for _name, code, rpc_gj, gj, pj, aj, rpc_w_gj, g_w_gj, p_w_gj, a_w_gj in rows:
        rpc_gm = json.loads(rpc_gj)
        g_gm = json.loads(gj)
        p_gm = json.loads(pj)
        a_gm = json.loads(aj)
        rpc_w_gm = json.loads(rpc_w_gj) if rpc_w_gj else None
        g_w_gm = json.loads(g_w_gj) if g_w_gj else None
        p_w_gm = json.loads(p_w_gj) if p_w_gj else None
        a_w_gm = json.loads(a_w_gj) if a_w_gj else None

        rpc_sq = geodesic_sq_miles(rpc_gm)
        g_sq = geodesic_sq_miles(g_gm)
        p_sq = geodesic_sq_miles(p_gm)
        a_sq = geodesic_sq_miles(a_gm)
        rpc_water_sq = geodesic_sq_miles(rpc_w_gm)
        g_water_sq = geodesic_sq_miles(g_w_gm)
        p_water_sq = geodesic_sq_miles(p_w_gm)
        a_water_sq = geodesic_sq_miles(a_w_gm)

        rpc_land_sq = rpc_sq - rpc_water_sq
        g_land_sq = g_sq - g_water_sq
        p_land_sq = p_sq - p_water_sq
        a_land_sq = a_sq - a_water_sq

        sums[0] += rpc_land_sq
        sums[1] += g_land_sq
        sums[2] += p_land_sq
        sums[3] += a_land_sq

        results.append({
            "code": code,
            "name": config.RPC_CODES.get(code, _name),
            "growth_sq_mi": round(g_land_sq, 1) if code in has_growth else None,
            "growth_pct": round(g_land_sq / rpc_land_sq * 100, 1) if rpc_land_sq > 0 and code in has_growth else None,
            "tier_pre_sq_mi": round(p_land_sq, 1) if code in has_pre else None,
            "tier_pre_pct": round(p_land_sq / rpc_land_sq * 100, 1) if rpc_land_sq > 0 and code in has_pre else None,
            "tier_app_sq_mi": round(a_land_sq, 1) if code in has_app else None,
            "tier_app_pct": round(a_land_sq / rpc_land_sq * 100, 1) if rpc_land_sq > 0 and code in has_app else None,
        })

    order = {c: i for i, c in enumerate(config.RPC_CODES)}
    results.sort(key=lambda r: order.get(r["code"], 999))

    total_rpc, total_g, total_p, total_a = sums
    results.append({
        "code": "VT",
        "name": "Statewide",
        "growth_sq_mi": round(total_g, 1),
        "growth_pct": round(total_g / total_rpc * 100, 1) if total_rpc > 0 else None,
        "tier_pre_sq_mi": round(total_p, 1),
        "tier_pre_pct": round(total_p / total_rpc * 100, 1) if total_rpc > 0 else None,
        "tier_app_sq_mi": round(total_a, 1),
        "tier_app_pct": round(total_a / total_rpc * 100, 1) if total_rpc > 0 else None,
    })

    return results


def build_flu_tier_stats(duck):
    rows = duck.execute("""
        SELECT flu_code,
               ST_AsGeoJSON(total_geom), ST_AsGeoJSON(overlap_geom),
               ST_AsGeoJSON(total_water_geom), ST_AsGeoJSON(overlap_water_geom)
        FROM flu_tier_data
    """).fetchall()

    results = []
    for code, total_json, overlap_json, total_w_json, overlap_w_json in rows:
        total_gm = json.loads(total_json)
        overlap_gm = json.loads(overlap_json)
        total_w_gm = json.loads(total_w_json) if total_w_json else None
        overlap_w_gm = json.loads(overlap_w_json) if overlap_w_json else None

        total_sq = geodesic_sq_miles(total_gm)
        overlap_sq = geodesic_sq_miles(overlap_gm)
        total_water_sq = geodesic_sq_miles(total_w_gm)
        overlap_water_sq = geodesic_sq_miles(overlap_w_gm)

        total_land_sq = total_sq - total_water_sq
        overlap_land_sq = overlap_sq - overlap_water_sq

        name = "All Growth Areas" if code == "ALL" else config.GROWTH_CODES.get(code, code)
        results.append({
            "code": code,
            "name": name,
            "total_sq_mi": round(total_land_sq, 1),
            "tier1b_sq_mi": round(overlap_land_sq, 1),
            "pct": round(overlap_land_sq / total_land_sq * 100, 1) if total_land_sq > 0 else None,
        })

    order = {c: i for i, c in enumerate(config.GROWTH_CODES)}
    results.sort(key=lambda r: (r["code"] == "ALL", order.get(r["code"], 99)))
    return results


def build_town_tier_stats(duck):
    has_tier = duck.execute("SELECT COUNT(*) FROM statewide_tier").fetchone()[0] > 0
    if not has_tier:
        return []

    rows = duck.execute("""
        SELECT name, geoid,
               ST_AsGeoJSON(town_geom),
               ST_AsGeoJSON(tier_overlap_geom),
               ST_AsGeoJSON(water_geom),
               ST_AsGeoJSON(tier_water_geom)
        FROM town_tier_stats_data
    """).fetchall()

    results = []
    for name, geoid, town_json, overlap_json, water_json, tier_water_json in rows:
        if not town_json:
            continue
        town_gm = json.loads(town_json)
        overlap_gm = json.loads(overlap_json) if overlap_json else None
        water_gm = json.loads(water_json) if water_json else None
        tier_water_gm = json.loads(tier_water_json) if tier_water_json else None

        town_sq = geodesic_sq_miles(town_gm)
        overlap_sq = geodesic_sq_miles(overlap_gm)
        water_sq = geodesic_sq_miles(water_gm)
        tier_water_sq = geodesic_sq_miles(tier_water_gm)

        town_land_sq = town_sq - water_sq
        overlap_land_sq = overlap_sq - tier_water_sq

        results.append({
            "name": name,
            "geoid": geoid,
            "total_sq_mi": round(town_land_sq, 2),
            "tier1b_sq_mi": round(overlap_land_sq, 2),
            "pct": round(overlap_land_sq / town_land_sq * 100, 1) if town_land_sq > 0 else 0.0,
        })

    return results


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
      --town-border: #888;
      --county-border: #444;
      --rpc-border: #222;
    }
    * { box-sizing: border-box; }
    html { margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: var(--ink); }
    body { margin: 0; background: #eef2f1; }
    header { border-bottom: 1px solid var(--line); background: var(--panel); }
    .header-inner { max-width: 1100px; margin: 0 auto; padding: 12px 14px; }
    h1 { margin: 0; font-size: 18px; line-height: 1.2; font-weight: 680; }
    .sub { margin-top: 3px; color: var(--muted); font-size: 13px; }
    .stats { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    .stat { min-width: 148px; padding: 7px 9px; border: 1px solid var(--line); border-radius: 6px; background: #f7f9fa; }
    .stat-value { display: block; font-size: 17px; line-height: 1.1; font-weight: 720; }
    .stat-label { display: block; margin-top: 2px; color: var(--muted); font-size: 11px; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: flex-end; }
    button { height: 34px; border: 1px solid var(--line); background: #fff; color: var(--ink); font: inherit; font-size: 13px; border-radius: 6px; padding: 0 11px; cursor: pointer; }
    button:hover { border-color: var(--accent); color: var(--accent-dark); }
    #map-wrapper, #tier-map-wrapper { position: relative; height: 55vh; max-width: 1100px; margin: 14px auto; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 6px rgba(0,0,0,0.1); }
    #map-wrapper.fullscreen { position: fixed; inset: 0; z-index: 9999; height: 100vh; max-width: none; width: 100vw; border-radius: 0; margin: 0; }
    #map, #tier-map { height: 100%; width: 100%; }
    .leaflet-popup-content { margin: 10px 12px; min-width: 220px; }
    .popup-title { font-weight: 700; margin-bottom: 6px; }
    .popup-grid { display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 4px 10px; font-size: 13px; }
    .popup-grid span:nth-child(odd) { color: var(--muted); }
    .info { padding: 9px 10px; background: rgba(255,255,255,0.96); border: 1px solid var(--line); border-radius: 6px; box-shadow: 0 1px 8px rgba(20,30,40,0.12); font-size: 13px; min-width: 170px; margin-top: 1em; }
    .info strong { display: block; margin-bottom: 4px; font-size: 14px; }
    .info .sec { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--line); }
    .legend-row { display: flex; align-items: center; gap: 7px; margin-top: 5px; }
    .swatch { width: 13px; height: 13px; border-radius: 3px; border: 1px solid rgba(0,0,0,0.25); flex-shrink: 0; }
    .leaflet-control-layers { margin-top: 1em !important; }
    .leaflet-control-fullscreen { width: 34px; height: 34px; background: #fff; border: 1px solid var(--line); border-radius: 4px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 16px; color: var(--ink); }
    .leaflet-control-fullscreen:hover { border-color: var(--accent); color: var(--accent-dark); }
    #mid-stats { max-width: 1100px; margin: 14px auto 0; padding: 0 14px; display: flex; flex-wrap: wrap; gap: 8px; }
    #mid-stats .stat { min-width: 148px; padding: 7px 9px; border: 1px solid var(--line); border-radius: 6px; background: var(--panel); }
    .data-table-wrap { max-width: 1100px; margin: 14px auto; padding: 0 14px; }
    .data-table-wrap:last-of-type { margin-bottom: 40px; }
    .data-table-wrap h2 { margin: 0 0 12px; font-size: 15px; font-weight: 680; }
    .data-table-wrap table { width: 100%; border-collapse: collapse; font-size: 13px; background: var(--panel); border-radius: 8px; box-shadow: 0 1px 6px rgba(0,0,0,0.1); overflow: hidden; }
    .data-table-wrap th, .data-table-wrap td { padding: 10px 14px; text-align: right; border-bottom: 1px solid var(--line); }
    .data-table-wrap th { font-weight: 600; color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; background: #f7f9fa; }
    .data-table-wrap th:first-child, .data-table-wrap td:first-child { text-align: left; }
    .data-table-wrap tbody tr:hover { background: #f7f9fa; }
    .data-table-wrap tfoot td { font-weight: 700; border-top: 2px solid var(--ink); border-bottom: none; background: #f7f9fa; }
    .blank { color: var(--muted); }
    .num { font-variant-numeric: tabular-nums; }
    @media (max-width: 760px) {
      header { grid-template-columns: 1fr; gap: 10px; }
      .toolbar { justify-content: flex-start; }
      #map-wrapper, #tier-map-wrapper { height: 40vh; margin: 10px; border-radius: 6px; }
      #rpc-table-wrap { padding: 0 10px; }
      #rpc-table-wrap th, #rpc-table-wrap td { padding: 8px 6px; font-size: 12px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      <h1>Act 181 Growth Areas and Tier 1B</h1>
      <div class="sub">FLU growth categories DC, VC, VA, and PGA classified by Tier 1B overlap</div>
    </div>
  </header>
  <main id="map-wrapper">
    <div id="map"></div>
  </main>
  <div class="stats" id="mid-stats">
    <div class="stat"><span class="stat-value" id="stat-total-growth">--</span><span class="stat-label">sq mi growth areas</span></div>
    <div class="stat"><span class="stat-value" id="stat-tier-growth">--</span><span class="stat-label">sq mi growth area + any Tier 1B</span></div>
    <div class="stat"><span class="stat-value" id="stat-tier-pct">--</span><span class="stat-label">growth area land mass with Tier 1B</span></div>
  </div>
  <section id="flu-tier-wrap" class="data-table-wrap">
    <h2>Growth Area Designations Overlapping Tier 1B</h2>
    <table>
      <thead>
        <tr>
          <th>Designation</th>
          <th>Total sq mi</th>
          <th>Tier 1B sq mi</th>
          <th>% in Tier 1B</th>
        </tr>
      </thead>
      <tbody id="flu-tier-tbody"></tbody>
      <tfoot id="flu-tier-tfoot"></tfoot>
    </table>
  </section>
  <section id="rpc-table-wrap" class="data-table-wrap">
    <h2>RPC Land Area in Growth Areas and Tier 1B</h2>
    <table>
      <thead>
        <tr>
          <th>RPC</th>
          <th>Growth Area (mi²)</th>
          <th>Tier 1B (Pre-App) (mi²)</th>
          <th>Tier 1B (Final App) (mi²)</th>
        </tr>
      </thead>
      <tbody id="rpc-tbody"></tbody>
      <tfoot id="rpc-tfoot"></tfoot>
    </table>
  </section>
  <section id="tier-choro-wrap" class="data-table-wrap">
    <h2>Tier 1B Coverage by Municipality</h2>
    <p style="font-size:13px;color:var(--muted);margin:0 0 12px;">Percentage of each town&rsquo;s land area with Tier&nbsp;1B designation (pre-app or final-app).</p>
    <div class="map-wrapper" id="tier-map-wrapper"><div id="tier-map"></div></div>
  </section>
  <script id="overlay-data" type="application/json">__GEOJSON__</script>
  <script id="towns-data" type="application/json">__TOWNS__</script>
  <script id="counties-data" type="application/json">__COUNTIES__</script>
  <script id="rpcs-data" type="application/json">__RPCS__</script>
  <script id="rpc-stats-data" type="application/json">__RPC_STATS__</script>
  <script id="flu-tier-stats-data" type="application/json">__FLU_TIER_STATS__</script>
  <script id="town-tier-stats-data" type="application/json">__TOWN_TIER_STATS__</script>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const data = JSON.parse(document.getElementById("overlay-data").textContent);
    const townsData = JSON.parse(document.getElementById("towns-data").textContent);
    const countiesData = JSON.parse(document.getElementById("counties-data").textContent);
    const rpcsData = JSON.parse(document.getElementById("rpcs-data").textContent);
    const rpcStats = JSON.parse(document.getElementById("rpc-stats-data").textContent);
    const fluTierStats = JSON.parse(document.getElementById("flu-tier-stats-data").textContent);

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
          fl.bindPopup('<div class="popup-title">' + esc(p.label||"") + '</div><div class="popup-grid"><span>RPC</span><span>' + esc(p.rpc||"") + '</span><span>Notes</span><span>' + esc(p.notes||"") + '</span></div>');
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
        + '<div class="legend-row"><span class="swatch" style="background:'+colors.growth_app_tier1b+'"></span><span>Growth Area with final application Tier 1B</span></div>'
        + '<div class="sec"><strong>Reference Layers</strong></div>'
        + '<div class="legend-row"><span class="swatch" style="background:transparent;border-color:var(--town-border)"></span><span>Town boundaries</span></div>'
        + '<div class="legend-row"><span class="swatch" style="background:transparent;border-color:var(--county-border);border-width:2px"></span><span>County boundaries</span></div>'
        + '<div class="legend-row"><span class="swatch" style="background:transparent;border-color:var(--rpc-border);border-width:2.5px"></span><span>RPC boundaries</span></div>';
      return d;
    };
    legend.addTo(map);

    const boundaryLayers = {};
    function addBoundaryLayer(fc, label, style, addToMap) {
      if (!fc || !fc.features || fc.features.length === 0) return null;
      const layer = L.geoJSON(fc, {
        style: style,
        onEachFeature(f, fl) {
          const p = f.properties || {};
          fl.bindPopup('<div class="popup-title">' + esc(p.name||p.label||"") + '</div><div class="popup-grid"><span>Type</span><span>' + esc(p.label||"") + '</span><span>GEOID</span><span>' + esc(p.geoid||"") + '</span></div>');
        }
      });
      boundaryLayers[label] = layer;
      if (allBounds) allBounds.extend(layer.getBounds());
      if (addToMap) layer.addTo(map);
      return layer;
    }

    addBoundaryLayer(townsData, "Towns", {
      color: "var(--town-border)", weight: 0.6, opacity: 0.7, fill: false
    }, true);
    addBoundaryLayer(countiesData, "Counties", {
      color: "var(--county-border)", weight: 1.4, opacity: 0.6, fill: false
    }, false);
    addBoundaryLayer(rpcsData, "RPCs", {
      color: "var(--rpc-border)", weight: 2.2, opacity: 0.5, fill: false
    }, true);

    const allLayers = {};
    Object.assign(allLayers, overlayLayers);
    Object.assign(allLayers, boundaryLayers);

    if (Object.keys(allLayers).length > 1) {
      L.control.layers(null, allLayers, { position: "topright" }).addTo(map);
    }

    L.Control.Fullscreen = L.Control.extend({
      options: { position: "topleft" },
      onAdd: function() {
        const btn = L.DomUtil.create("button", "leaflet-control-fullscreen");
        btn.innerHTML = "\\u26F6";
        btn.title = "Toggle fullscreen";
        const wrapper = document.getElementById("map-wrapper");
        L.DomEvent.on(btn, "click", function() {
          wrapper.classList.toggle("fullscreen");
          map.invalidateSize();
          btn.innerHTML = wrapper.classList.contains("fullscreen") ? "\\u2715" : "\\u26F6";
          if (wrapper.classList.contains("fullscreen")) {
            document.body.style.overflow = "hidden";
          } else {
            document.body.style.overflow = "";
          }
        });
        return btn;
      }
    });
    new L.Control.Fullscreen().addTo(map);

    document.addEventListener("keydown", function(e) {
      if (e.key === "Escape") {
        const wrapper = document.getElementById("map-wrapper");
        if (wrapper.classList.contains("fullscreen")) {
          wrapper.classList.remove("fullscreen");
          map.invalidateSize();
          document.body.style.overflow = "";
          document.querySelector(".leaflet-control-fullscreen").innerHTML = "\\u26F6";
        }
      }
    });

    const s = (data.metadata||{}).area_stats||{};
    document.getElementById("stat-total-growth").textContent = fmtNumber(s.total_growth_sq_mi, 1);
    document.getElementById("stat-tier-growth").textContent = fmtNumber(s.growth_with_any_tier1b_sq_mi, 1);
    document.getElementById("stat-tier-pct").textContent = fmtNumber(s.growth_with_any_tier1b_pct, 1) + "%";
    if (allBounds && allBounds.isValid()) map.fitBounds(allBounds, {padding:[18,18]});

    function pctCell(v) {
      if (v == null) return '<span class="blank">&mdash;</span>';
      return '<span class="num">' + fmtNumber(v, 1) + '%</span>';
    }

    function sqmiPctCell(sqMi, pct) {
      if (sqMi == null) return '<span class="blank">&mdash;</span>';
      if (pct == null) return '<span class="num">' + fmtNumber(sqMi, 1) + 'mi²</span>';
      return '<span class="num">' + fmtNumber(sqMi, 1) + 'mi² (' + fmtNumber(pct, 1) + '%)</span>';
    }

    function renderRpcTable(stats) {
      const tbody = document.getElementById("rpc-tbody");
      const tfoot = document.getElementById("rpc-tfoot");
      let html = "";
      for (let i = 0; i < stats.length; i++) {
        const r = stats[i];
        const row = '<tr>'
          + '<td>' + esc(r.name) + '</td>'
          + '<td>' + sqmiPctCell(r.growth_sq_mi, r.growth_pct) + '</td>'
          + '<td>' + sqmiPctCell(r.tier_pre_sq_mi, r.tier_pre_pct) + '</td>'
          + '<td>' + sqmiPctCell(r.tier_app_sq_mi, r.tier_app_pct) + '</td>'
          + '</tr>';
        if (r.code === "VT") {
        } else {
          html += row;
        }
      }
      tbody.innerHTML = html;
      const sw = stats[stats.length - 1];
      tfoot.innerHTML = '<tr>'
        + '<td>' + esc(sw.name) + '</td>'
        + '<td>' + sqmiPctCell(sw.growth_sq_mi, sw.growth_pct) + '</td>'
        + '<td>' + sqmiPctCell(sw.tier_pre_sq_mi, sw.tier_pre_pct) + '</td>'
        + '<td>' + sqmiPctCell(sw.tier_app_sq_mi, sw.tier_app_pct) + '</td>'
        + '</tr>';
    }

    renderRpcTable(rpcStats);

    function renderFluTierTable(stats) {
      const tbody = document.getElementById("flu-tier-tbody");
      const tfoot = document.getElementById("flu-tier-tfoot");
      let html = "";
      for (const r of stats) {
        const row = '<tr>'
          + '<td>' + esc(r.name) + '</td>'
          + '<td class="num">' + fmtNumber(r.total_sq_mi, 1) + '</td>'
          + '<td class="num">' + fmtNumber(r.tier1b_sq_mi, 1) + '</td>'
          + '<td>' + pctCell(r.pct) + '</td>'
          + '</tr>';
        if (r.code === "ALL") {
          tfoot.innerHTML = row;
        } else {
          html += row;
        }
      }
      tbody.innerHTML = html;
    }

    renderFluTierTable(fluTierStats);

    function getTierColor(pct) {
      return pct > 50 ? '#084594' :
             pct > 25 ? '#2171b5' :
             pct > 10 ? '#4292c6' :
             pct > 5  ? '#6baed6' :
             pct > 0  ? '#bdd7e7' :
                        '#f7f7f7';
    }

    const townTierStats = JSON.parse(document.getElementById("town-tier-stats-data").textContent);
    const townStatsByGeoid = {};
    townTierStats.forEach(function(r) { townStatsByGeoid[r.geoid] = r; });

    const tierMap = L.map("tier-map", { zoomControl: true }).setView([44.05, -72.7], 8);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(tierMap);

    const choroLayer = L.geoJSON(townsData, {
      style: function(f) {
        var s = townStatsByGeoid[f.properties.geoid];
        var pct = s ? s.pct : 0;
        return {
          fillColor: getTierColor(pct),
          weight: 0.8,
          opacity: 0.6,
          color: '#666',
          fillOpacity: 0.75
        };
      },
      onEachFeature: function(f, layer) {
        var s = townStatsByGeoid[f.properties.geoid];
        if (s) {
          layer.bindPopup('<strong>' + esc(f.properties.name) + '</strong><br>'
            + 'Tier 1B: ' + fmtNumber(s.tier1b_sq_mi, 2) + 'mi² (' + fmtNumber(s.pct, 2) + '%)');
        }
        layer.on({
          mouseover: function(e) {
            e.target.setStyle({ weight: 2, color: '#333', fillOpacity: 0.9 });
            e.target.bringToFront();
          },
          mouseout: function(e) { choroLayer.resetStyle(e.target); }
        });
      }
    }).addTo(tierMap);

    var choroBounds;
    if (choroLayer.getLayers().length > 0) {
      choroBounds = choroLayer.getBounds();
      if (choroBounds.isValid()) tierMap.fitBounds(choroBounds, { padding: [18, 18] });
    }

    var choroLegend = L.control({ position: "bottomright" });
    choroLegend.onAdd = function() {
      var div = L.DomUtil.create("div", "info");
      div.innerHTML = '<strong>Tier 1B Coverage</strong>';
      var grades = [0, 5, 10, 25, 50];
      for (var i = 0; i < grades.length; i++) {
        var from = grades[i];
        var to = grades[i + 1];
        var color = getTierColor(from + 0.01);
        div.innerHTML += '<div class="legend-row"><span class="swatch" style="background:' + color + '"></span>'
          + from + '%' + (to ? '&ndash;' + to + '%' : '+') + '</div>';
      }
      return div;
    };
    choroLegend.addTo(tierMap);
  </script>
</body>
</html>
"""


def write_overlay(fc, path):
    path.write_text(json.dumps(fc, separators=(",", ":")))
    print(f"wrote {path}")
    meta = fc.get("metadata", {})
    print(json.dumps(meta.get("area_stats", {}), indent=2))


def write_boundary_layer(layer, path):
    path.write_text(json.dumps(layer, separators=(",", ":")))
    print(f"wrote {path}  ({len(layer['features'])} features)")


def write_leaflet(geojson_path, html_path, towns_fc, counties_fc, rpcs_fc, rpc_stats, flu_tier_stats, town_tier_stats):
    geojson = geojson_path.read_text()
    geojson = geojson.replace("</script", "<\\/script")

    def dump(fc):
        text = json.dumps(fc, separators=(",", ":"))
        return text.replace("</script", "<\\/script")

    rpc_json = json.dumps(rpc_stats, separators=(",", ":"))
    flu_json = json.dumps(flu_tier_stats, separators=(",", ":"))
    town_tier_json = json.dumps(town_tier_stats, separators=(",", ":"))

    html = (LEAFLET_TEMPLATE
        .replace("__GEOJSON__", geojson)
        .replace("__TOWNS__", dump(towns_fc))
        .replace("__COUNTIES__", dump(counties_fc))
        .replace("__RPCS__", dump(rpcs_fc))
        .replace("__RPC_STATS__", rpc_json)
        .replace("__FLU_TIER_STATS__", flu_json)
        .replace("__TOWN_TIER_STATS__", town_tier_json)
    )
    html_path.write_text(html)
    print(f"wrote {html_path}")


def main():
    config.OUT_DIR.mkdir(parents=True, exist_ok=True)

    duck = duckdb.connect(str(config.DB_PATH), read_only=True)
    duck.execute("LOAD spatial;")

    overlay = build_overlay(duck)

    towns_fc = load_boundary_layer(duck, "town", "Towns",
        {"color": "#888", "weight": 0.6, "opacity": 0.7, "fill": False})
    counties_fc = load_boundary_layer(duck, "county", "Counties",
        {"color": "#444", "weight": 1.4, "opacity": 0.6, "fill": False})
    rpcs_fc = load_boundary_layer(duck, "rpc", "RPCs",
        {"color": "#222", "weight": 2.2, "opacity": 0.5, "fill": False})

    rpc_stats = build_rpc_stats(duck)
    flu_tier_stats = build_flu_tier_stats(duck)
    town_tier_stats = build_town_tier_stats(duck)

    duck.close()

    overlay_path = config.OUT_DIR / "growth_tier_overlay.geojson"
    html_path = config.OUT_DIR / "index.html"

    write_overlay(overlay, overlay_path)
    write_leaflet(overlay_path, html_path, towns_fc, counties_fc, rpcs_fc, rpc_stats, flu_tier_stats, town_tier_stats)
    print("Done")


if __name__ == "__main__":
    main()
