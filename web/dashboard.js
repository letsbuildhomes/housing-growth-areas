(async () => {
  'use strict';
  const loadStatus = document.getElementById('data-status');
  let data, mapData, tierData, housingData;
  try {
    [data, mapData, tierData, housingData] = await Promise.all(['interim-areas.json', 'map.json', 'tier1b.json', 'housing-growth.json'].map(async name => {
      const response = await fetch(`./data/${name}`);
      if (!response.ok) throw new Error(`Could not load ${name}: HTTP ${response.status}`);
      return response.json();
    }));
    if (data.schema_version !== 1 || mapData.schema_version !== 2 || tierData.schema_version !== 3 || housingData.schema_version !== 1 ||
        !Array.isArray(housingData.coverage_parts?.features) ||
        ['snapshot_id', 'captured_at', 'exported_at'].some(key => !data[key] || [mapData, tierData, housingData].some(exportData => data[key] !== exportData[key]))) {
      throw new Error('The table and map exports do not match.');
    }
  } catch (error) {
    loadStatus.setAttribute('role', 'alert');
    loadStatus.textContent = location.protocol === 'file:'
      ? 'Preview this dashboard with make serve, or open its published website URL.'
      : 'Unable to load dashboard data. Please reload the page. If this persists, check that the complete data folder was uploaded alongside index.html.';
    console.error(error);
    return;
  }
  loadStatus.hidden = true;
  const table = document.getElementById('areas-table');
  const search = document.getElementById('search');
  const eligibility = document.getElementById('eligibility');
  const category = document.getElementById('category');
  const fields = ['likely_eligible', 'zoning_bylaws'];
  const status = value => value === true ? 'yes' : value === false ? 'no' : 'unknown';
  const displayMunicipality = name => name === name.toUpperCase()
    ? name.toLowerCase().replace(/\b\w/g, letter => letter.toUpperCase()) : name;
  const number = value => value.toLocaleString('en-US');
  const captured = new Date(data.captured_at);
  document.getElementById('capture-date').textContent = captured.toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric', timeZone:'UTC'});
  document.getElementById('source-meta').textContent = `Source view: ${data.source_view} · Snapshot: ${data.snapshot_id} · Exported ${new Date(data.exported_at).toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric', timeZone:'UTC'})}`;

  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[character]));
  // CSS owns the brand and map palette; overlays and legend share the same values.
  const theme = getComputedStyle(document.documentElement);
  const themeColor = name => theme.getPropertyValue(name).trim();
  const mapColors = {positive: themeColor('--map-positive'), negative: themeColor('--map-negative'),
    unknown: themeColor('--map-unknown'), absent: themeColor('--map-absent')};
  for (const [key, property] of Object.entries({partial: 'partial', neutral: 'neutral', villageArea: 'village-area',
    villageCenter: 'village-center', plannedGrowth: 'planned-growth', downtown: 'downtown'})) {
    mapColors[key] = themeColor(`--map-${property}`);
  }
  const housingSummaries = new Map(housingData.municipalities.map(p => [p.geoid, p]));
  let municipalityView = 'growth';
  // Map stage is each region's furthest submitted map; approval is its final stage.
  const stageLabels = {pre_application: 'Pre-application', application: 'Application', approved: 'Approved'};
  const stageLabel = value => stageLabels[value] || value || 'Not submitted';
  const stageLine = (stage, tierStage = stage) => `<div class="area-hover-type">Submission stage: ${escapeHTML(stageLabel(stage))}${
    tierStage !== stage ? ` (Tier 1B: ${escapeHTML(stageLabel(tierStage))})` : ''}</div>`;
  const percent = value => value == null ? 'Unknown' : value > 0 && value < 0.001 ? '<0.1%' : `${(value * 100).toFixed(1)}%`;
  const acreCount = value => (value / 4046.8564224).toLocaleString('en-US', {maximumFractionDigits: 1});
  const acres = value => value == null ? 'Unknown' : `${acreCount(value)} acres`;
  const rpcNames = {AC: 'ACRPC', BC: 'BCRC', CV: 'CVRPC', CC: 'CCRPC',
    LC: 'LCPC', MA: 'MARC', NV: 'NVDA', NW: 'NRPC', RR: 'RRPC', TR: 'TRORC', WR: 'WRC'};
  const rpcName = rpc => rpcNames[rpc] || rpc || 'Unknown region';
  const placeHeading = (name, rpc) => `<strong class="area-hover-name">${escapeHTML(name)} <span class="area-hover-region">· ${escapeHTML(rpcName(rpc))}</span></strong>`;
  const plural = (count, noun) => `${number(count)} ${noun}${count === 1 ? '' : 's'}`;
  function municipalityTooltip(props) {
    const p = housingSummaries.get(props.geoid);
    const heading = placeHeading(props.name || props.municipality, props.focus_rpc || p?.rpc);
    const stage = stageLine(housingData.selected_stages[p?.rpc], municipalityView === 'growth'
      ? housingData.selected_stages[p?.rpc] : housingData.tier_selected_stages[p?.rpc]);
    if (!p?.block_count) {
      return `${heading}<div class="area-hover-type">${p?.status === 'no_housing' ? 'No Housing Growth Areas' : 'Cannot assess Housing Growth Areas'}</div>${stage}`;
    }
    if (municipalityView === 'growth') {
      return `${heading}<div class="area-hover-type">${plural(p.block_count, 'Housing Growth Area')}<br>${acres(p.area_m2)}${
        p.municipality_area_m2 ? ` · ${percent(p.area_m2 / p.municipality_area_m2)} of ${escapeHTML(props.name || props.municipality)}` : ''}</div>${stage}`;
    }
    // List every nonzero outcome so partly mapped areas are never folded into "not mapped".
    const outcomes = [[p.substantial_count, 'mapped as Tier 1B'], [p.partial_count, 'partly mapped'],
      [p.none_count, 'not mapped'], [p.unknown_count, 'cannot assess']]
      .filter(([count]) => count).map(([count, label]) => `${number(count)} ${label}`).join(' · ');
    return `${heading}<div class="area-hover-type">${plural(p.block_count, 'Housing Growth Area')}<br>${outcomes}<br>${percent(p.coverage_fraction)} of ${acres(p.area_m2)} mapped as Tier 1B</div>${stage}`;
  }
  const areaColor = value => value === true ? mapColors.positive : value === false ? mapColors.negative : mapColors.unknown;
  const areaDetails = new Map(data.municipalities.flatMap(group =>
    group.areas.map(area => [area.feature_id, area])));
  const criteria = [
    ['zoning_bylaws', 'Zoning / bylaws'], ['drinking_water', 'Drinking water'],
    ['sewer_wastewater', 'Sewer / wastewater'], ['adequate_soils', 'Adequate soils'],
  ];
  function areaTooltip(props) {
    const details = areaDetails.get(props.feature_id) || props;
    const state = status(props.likely_eligible);
    const determination = state === 'yes' ? 'Exempt' : state === 'no' ? 'Not exempt' : 'Exemption Unknown';
    const criterionRow = ([field, label]) => {
      const value = status(details[field]);
      return `<tr><th scope="row">${label}</th><td class="${value}">${value === 'yes' ? 'Yes' : value === 'no' ? 'No' : 'Unknown'}</td></tr>`;
    };
    const infrastructure = status(EligibilityDisplay.infrastructure(details));
    return `<strong class="area-hover-name">${escapeHTML(props.name || props.category || 'Interim area')}</strong>
      <div class="area-hover-town">${escapeHTML(displayMunicipality(props.municipality || 'Unknown municipality'))}</div>
      <div class="area-hover-type">${escapeHTML(details.exemption_type || details.category_label || props.category)}</div>
      <div class="area-hover-status ${state}">${determination}</div>
      <small class="publisher-label">Publisher-reported</small>
      ${EligibilityDisplay.zoningApplies(details) ? `<table class="area-hover-criteria" aria-label="Zoning requirement"><tbody>${criterionRow(criteria[0])}</tbody></table>` : ''}
      <div class="infrastructure-heading"><strong>Infrastructure · any one</strong><span class="${infrastructure}">${infrastructure === 'yes' ? 'Met' : infrastructure === 'no' ? 'Not met' : 'Unknown'}</span></div>
      <table class="area-hover-criteria" aria-label="Infrastructure alternatives"><tbody>${criteria.slice(1).map(criterionRow).join('')}</tbody></table>`;
  }

  function initMap() {
    const gain = themeColor('--map-gain');
    const {steps, groups, overlays, initial: initialStyle = () => ({})} = MapStories.create({mapData, tierData, housingData,
      colors: {...mapColors, gain}, areaColor});
    // Leaflet's SVG renderers draw a margin beyond the view (default 10% per side);
    // a wider margin keeps short drags from revealing undrawn polygons.
    const renderers = new Map();
    const rendererFor = pane => renderers.get(pane) || renderers.set(pane, L.svg({pane, padding: 0.5})).get(pane);
    const map = L.map('map', {zoomControl: true, scrollWheelZoom: false, fadeAnimation: false, renderer: L.svg({padding: 0.5}),
      zoomSnap: 0.25, zoomDelta: 0.5, minZoom: 6, maxZoom: 19});
    const HoverTooltip = L.Tooltip.extend({
      options: {sticky: true, opacity: 0.9, className: 'area-hover'},
      _setPosition(position) {
        const point = this._map.layerPointToContainerPoint(position);
        const bounds = this._map.getContainer().getBoundingClientRect();
        const box = this._container;
        // Prefer above the pointer; flip below when the box would leave the view.
        const above = bounds.top + point.y - Math.max(0, bounds.top) >= box.offsetHeight + 16;
        const x = bounds.left + point.x;
        const left = Math.max(0, bounds.left) + 8 + box.offsetWidth / 2;
        const right = Math.min(innerWidth, bounds.right) - 8 - box.offsetWidth / 2;
        this.options.direction = above ? 'top' : 'bottom';
        this.options.offset = [Math.max(left, Math.min(right, x)) - x, above ? -10 : 10];
        L.Tooltip.prototype._setPosition.call(this, position);
      },
    });
    const hoverBox = new HoverTooltip();
    const hoverTargets = new WeakMap();
    let activeHover = null, mapMoving = false;
    function registerHover(layer, content, kind) {
      const register = () => {
        const element = layer.getElement();
        if (element) hoverTargets.set(element, {layer, content, kind});
      };
      layer.on('add', register);
      layer.on('remove', () => { if (activeHover === layer) clearHover(); });
      register();
    }
    map.attributionControl.setPrefix(false);
    const trackpad = MapInteractions.trackpadZoom(map);
    // Leaflet ends a drag only on mouseup, which is lost when the button is released outside
    // the map or window. Supply that mouseup once the pointer leaves the map's bounds or the
    // window, the window loses focus, or the pointer returns with no button held.
    let dragArmed = false;
    const endDrag = event => {
      if (!dragArmed) return;
      dragArmed = false;
      document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, clientX: event?.clientX ?? 0, clientY: event?.clientY ?? 0}));
    };
    map.getContainer().addEventListener('mousedown', event => {dragArmed = event.button === 0;});
    document.addEventListener('mouseup', () => {dragArmed = false;});
    // Capture runs before Leaflet's document listener, so a lost release never pans the map.
    document.addEventListener('mousemove', event => {
      if (!dragArmed) return;
      const bounds = map.getContainer().getBoundingClientRect();
      if (event.buttons === 0 || event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom) endDrag(event);
    }, {capture: true, passive: true});
    document.documentElement.addEventListener('mouseleave', endDrag);
    window.addEventListener('blur', () => endDrag());
    const basemapStatus = document.getElementById('basemap-status');
    const basemap = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    });
    basemap.on('tileerror', () => { basemapStatus.hidden = false; });
    basemap.on('loading', () => { basemapStatus.hidden = true; });
    basemap.addTo(map);
    // Municipalities take hover only in stories that fill them.
    const townHover = steps.some(step => step.municipalFill);
    const townLayer = L.geoJSON(mapData.towns, {
      interactive: townHover,
      style: feature => ({color: '#536c70', weight: 1, opacity: 0.85,
        fillColor: '#788992', fillOpacity: 0}),
      onEachFeature: (feature, layer) => townHover && registerHover(layer, () => municipalityTooltip(feature.properties), 'town'),
    }).addTo(map);
    map.createPane('rpcBoundaries');
    map.getPane('rpcBoundaries').style.zIndex = 450;
    map.getPane('rpcBoundaries').style.pointerEvents = 'none';
    const rpcLayer = L.geoJSON(mapData.rpcs, {
      pane: 'rpcBoundaries', renderer: rendererFor('rpcBoundaries'), interactive: false,
      style: {color: themeColor('--brand-green'), weight: 1.6, opacity: 0.8, fill: false},
    }).addTo(map);
    map.createPane('storyAreas');
    map.getPane('storyAreas').style.zIndex = 440;
    const areaLayer = L.geoJSON(mapData.areas, {
      pane: 'storyAreas', renderer: rendererFor('storyAreas'),
      style: feature => ({color: areaColor(feature.properties.likely_eligible), weight: 1.2,
        opacity: 0.9, fillColor: areaColor(feature.properties.likely_eligible), fillOpacity: 0.42}),
      onEachFeature: (feature, layer) => {
        registerHover(layer, () => areaTooltip(feature.properties), 'area');
      }
    });
    const {positive: good, negative: bad, unknown: muted, absent} = mapColors;
    const tierColor = good;
    const tierPane = map.createPane('tierWorking');
    tierPane.style.zIndex = 430;
    const tierLayer = L.geoJSON(tierData.areas, {
      pane: 'tierWorking', renderer: rendererFor('tierWorking'),
      style: {color: tierColor, fillColor: tierColor, weight: 1.2, opacity: 0, fillOpacity: 0},
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        registerHover(layer, () => `${placeHeading(p.municipality, p.rpc)}
          <div class="area-hover-type">Tier 1B</div>${stageLine(p.map_stage)}`, 'tier');
      },
    });
    map.createPane('housingGrowth').style.zIndex = 441;
    // Housing Growth Area hover shading sits above categories and never takes hover.
    const outlinePane = map.createPane('housingOutlines');
    outlinePane.style.zIndex = 442;
    outlinePane.style.pointerEvents = 'none';
    const categoryLabels = {VA: 'Village Area', VC: 'Village Center', PGA: 'Planned Growth Area', DC: 'Downtown Center'};
    const place = p => `<div class="area-hover-town">${escapeHTML(p.municipality || 'Unknown municipality')} · ${escapeHTML(rpcName(p.rpc))}</div>`;
    const coverageTitles = {covered: 'Mapped as Tier 1B', uncovered: 'Not mapped as Tier 1B', unknown: 'Tier 1B status unknown'};
    // Green and red pieces share one template; only the coverage title differs.
    function housingTooltip(kind, p) {
      if (kind === 'housing-category') {
        return `<strong class="area-hover-name">${escapeHTML(categoryLabels[p.flu_code])}</strong>${place(p)}${stageLine(p.map_stage)}`;
      }
      const share = p.area_m2 ? p.portion_area_m2 / p.area_m2 : null;
      const size = share >= 0.9995 ? `All ${acres(p.area_m2)} of this Housing Growth Area`
        : `${acres(p.portion_area_m2)} of this ${acreCount(p.area_m2)}-acre Housing Growth Area (${percent(share)})`;
      return `<strong class="area-hover-name">${coverageTitles[p.coverage_kind] || coverageTitles.unknown}</strong>${place(p)}
        <div class="area-hover-type">${size}</div>${stageLine(p.map_stage, p.tier_map_stage)}`;
    }
    // Split pieces under one acre are display slivers; whole small areas still show.
    const coverageCounts = new Map();
    housingData.coverage_parts.features.forEach(({properties: p}) => coverageCounts.set(p.block_id, (coverageCounts.get(p.block_id) || 0) + 1));
    const coverageParts = {...housingData.coverage_parts, features: housingData.coverage_parts.features.filter(({properties: p}) =>
      coverageCounts.get(p.block_id) === 1 || p.portion_area_m2 >= 4046.8564224)};
    const housingLayers = [
      ['housing-category', housingData.categories], ['housing-block', housingData.blocks], ['housing-coverage', coverageParts],
    ].map(([kind, collection]) => ({kind, layer: L.geoJSON(collection, {
      pane: kind === 'housing-block' ? 'housingOutlines' : 'housingGrowth', interactive: kind !== 'housing-block',
      renderer: rendererFor(kind === 'housing-block' ? 'housingOutlines' : 'housingGrowth'),
      style: {color: good, fillColor: good, weight: 1, opacity: 0, fillOpacity: 0},
      onEachFeature: (feature, layer) => {
        if (kind !== 'housing-block') {
          registerHover(layer, () => housingTooltip(kind, feature.properties), kind);
        }
      },
    })}));
    // Keep story collections in memory; mount their polygons only while visible.
    const storyLayers = [['area', areaLayer], ['tier', tierLayer], ...housingLayers.map(({kind, layer}) => [kind, layer])]
      .filter(([kind]) => !overlays || overlays.includes(kind));
    // Hover tint: the hovered polygon's fill darkens slightly; over category polygons,
    // the whole Housing Growth Area (block) under the pointer is shaded instead.
    const sampledStyles = new Map();
    let tintedLayer = null;
    let storyOrderChanged = false;
    const darken = color => /^#[0-9a-f]{6}$/i.test(color) ? '#' + color.slice(1).match(/../g)
      .map(value => Math.round(parseInt(value, 16) * 0.8).toString(16).padStart(2, '0')).join('') : color;
    const blockCollection = housingLayers.find(({kind}) => kind === 'housing-block').layer;
    const blocksByTown = new Map();
    blockCollection.eachLayer(layer => {
      const key = `${layer.feature.properties.rpc}:${layer.feature.properties.geoid}`;
      blocksByTown.set(key, [...(blocksByTown.get(key) || []), layer]);
    });
    const tint = (layer, style) => blockCollection.hasLayer(layer) ? {...style, fillColor: '#000000', fillOpacity: 0.15}
      : style.fillColor ? {...style, fillColor: darken(style.fillColor)} : style;
    const paint = layer => {
      const style = sampledStyles.get(layer);
      if (!style) return;
      const rendered = layer === tintedLayer ? tint(layer, style) : style;
      layer.setStyle(rendered);
      const visible = (layer.options.stroke && layer.options.opacity > 0) ||
        (layer.options.fill && layer.options.fillOpacity > 0);
      if (visible && !map.hasLayer(layer)) {
        layer.addTo(map);
        storyOrderChanged = true;
      } else if (!visible && map.hasLayer(layer)) {
        map.removeLayer(layer);
      }
    };
    function restoreStoryOrder() {
      if (!storyOrderChanged) return;
      // Re-added SVG paths otherwise sit above later layers in the same pane.
      storyLayers.forEach(([, collection]) => collection.eachLayer(layer => {
        if (map.hasLayer(layer) && layer.getElement()) layer.bringToFront();
      }));
      storyOrderChanged = false;
    }
    function setTint(layer) {
      if (layer === tintedLayer) return;
      const previous = tintedLayer;
      tintedLayer = layer;
      if (previous) paint(previous);
      if (layer) paint(layer);
      restoreStoryOrder();
    }
    const inRing = ([x, y], ring) => {
      let inside = false;
      for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const [xi, yi] = ring[i], [xj, yj] = ring[j];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
      }
      return inside;
    };
    const contains = ({type, coordinates}, point) => (type === 'Polygon' ? [coordinates] : type === 'MultiPolygon' ? coordinates : [])
      .some(([outer, ...holes]) => inRing(point, outer) && !holes.some(hole => inRing(point, hole)));
    // Category and block display shapes are simplified separately; a one-block town needs no test.
    const blockAt = (latlng, p) => {
      const candidates = blocksByTown.get(`${p.rpc}:${p.geoid}`) || [];
      return candidates.find(block => contains(block.feature.geometry, [latlng.lng, latlng.lat]))
        || (candidates.length === 1 ? candidates[0] : null);
    };
    function clearHover() {
      activeHover = null;
      hoverBox.close();
      setTint(null);
    }
    map.on('movestart zoomstart', () => { mapMoving = true; clearHover(); });
    map.on('moveend', () => { mapMoving = false; });
    function followPointer(event) {
      if (mapMoving || dragArmed || event.buttons || trackpad.isActive()) { clearHover(); return; }
      // Hit-test the actual pointer position, including cards and controls above the map.
      const target = document.elementFromPoint(event.clientX, event.clientY);
      const hovered = target && hoverTargets.get(target);
      if (!hovered || !map.hasLayer(hovered.layer)) { clearHover(); return; }
      const latlng = map.mouseEventToLatLng(event);
      if (activeHover !== hovered.layer) {
        activeHover = hovered.layer;
        hoverBox.setContent(hovered.content());
      }
      setTint(hovered.kind === 'housing-category' ? blockAt(latlng, hovered.layer.feature.properties) : hovered.layer);
      hoverBox.setLatLng(latlng).openOn(map);
    }
    const mapContainer = map.getContainer();
    mapContainer.addEventListener('pointermove', event => {
      if (event.pointerType === 'touch') clearHover();
      else followPointer(event);
    });
    // Preserve tap-to-inspect on phones without leaving boxes open during a drag.
    mapContainer.addEventListener('pointerup', event => { if (event.pointerType === 'touch') followPointer(event); });
    mapContainer.addEventListener('pointerdown', clearHover);
    mapContainer.addEventListener('pointerleave', clearHover);
    window.addEventListener('blur', clearHover);
    let focusRpc = null;
    const townRpcs = new Map(mapData.towns.features.map(f => [f.properties.geoid, f.properties.focus_rpc]));
    // Step keys count municipalities by default, or Housing Growth Areas when a step asks.
    const countStat = (step, predicate) => (step.statsOf === 'areas'
      ? housingData.blocks.features.filter(f => (!focusRpc || townRpcs.get(f.properties.geoid) === focusRpc) && predicate(f.properties))
      : mapData.towns.features.filter(f => (!focusRpc || f.properties.focus_rpc === focusRpc) && predicate(f.properties))).length;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const initial = [];
    townLayer.eachLayer(layer => initial.push({layer, kind: 'town', props: layer.feature.properties,
      style: {fillColor: layer.feature.properties.has_designated_area ? good : absent, fillOpacity: 0}}));
    storyLayers.forEach(([kind, collection]) => collection.eachLayer(layer => initial.push({layer, kind,
      props: layer.feature.properties, style: {color: good, fillColor: good, opacity: 0, fillOpacity: 0}})));
    initial.forEach(item => {item.style = {...item.style, ...initialStyle(item)};});
    const timeline = MapStoryAnimation.compile(initial, groups);
    let currentStep = 0, lastPosition = null;
    // Leaflet creates SVG paths only once the map has a view; apply styles and
    // restore their order after that first view too.
    map.whenReady(() => {lastPosition = null; storyOrderChanged = true;});
    const scrollLayout = window.matchMedia('(min-width: 1000px) and (min-height: 700px)');
    const walkthrough = document.getElementById('map-walkthrough');
    walkthrough.style.setProperty('--story-height', `${100 + (steps.length - 1) * 125}vh`);
    const stage = walkthrough.querySelector('.map-stage');
    const previous = document.getElementById('story-prev');
    const next = document.getElementById('story-next');
    const progress = document.getElementById('story-progress');
    const originalCard = document.querySelector('.map-story');
    const cards = steps.map((step, index) => {
      const card = originalCard.cloneNode(false);
      card.setAttribute('aria-label', step.title);
      card.innerHTML = `<div class="story-content"><div class="story-copy">
        <h3>${escapeHTML(step.title)}</h3><p class="story-description">${escapeHTML(step.description)}</p>
        </div><div class="story-key"><h4>${escapeHTML(step.statsTitle || 'Municipalities')}${step.stats.some(stat => stat.color) ? ' · map key' : ''}</h4>
        <div class="story-stats">${step.stats.map(({select, label, color}) => color
          ? `<div class="story-stat" style="--stat-color:${color}"><i class="stat-swatch" aria-hidden="true"></i><strong>${number(countStat(step, select))}</strong><span>${escapeHTML(label)}</span></div>`
          : `<div class="story-stat plain"><strong>${number(countStat(step, select))}</strong><span>${escapeHTML(label)}</span></div>`).join('')}</div>
        ${step.areaKey.length ? `<div class="story-area-key"><h4>Area polygons</h4><div>${step.areaKey.map(([color, label, shape]) =>
          `<span><i class="${shape === 'outline' ? 'key-outline' : ''}" style="${shape === 'outline' ? 'border-color' : 'background'}:${color}" aria-hidden="true"></i>${escapeHTML(label)}</span>`).join('')}</div></div>` : ''}
        </div></div>`;
      originalCard.before(card);
      return card;
    });
    originalCard.remove();
    progress.innerHTML = steps.map((step, index) => `<button type="button" class="story-stop"
      style="--stop:${index / (steps.length - 1) * 100}%;left:var(--stop)" aria-label="${escapeHTML(step.title)}" title="${escapeHTML(step.title)}"></button>`).join('');
    [...progress.children].forEach((dot, index) => dot.addEventListener('click', () => navigateStep(index)));
    function renderChapter(chapter, mapPosition) {
      const bounded = Math.max(0, Math.min(steps.length - 1, chapter));
      const state = MapStoryAnimation.scrollState(bounded, timeline.stops);
      const index = Math.round(bounded);
      if (index !== currentStep) {
        clearHover();
      }
      currentStep = index;
      municipalityView = steps[index].municipalityView || 'coverage';
      // Filled municipalities own hover; otherwise only area polygons respond.
      map.getContainer().classList.toggle('municipal-hover', !!steps[index].municipalFill);
      const position = reducedMotion.matches ? timeline.stops[index] : (mapPosition ?? state.position);
      if (position !== lastPosition) {
        timeline.sample(position).forEach(item => {
          sampledStyles.set(item.layer, item.style);
          paint(item.layer);
          if (item.kind !== 'town') {
            item.layer.getElement()?.classList.toggle('story-area-hidden', item.style.opacity === 0);
          }
        });
        restoreStoryOrder();
        lastPosition = position;
      }
      const moving = scrollLayout.matches && !reducedMotion.matches;
      const cardFrom = Math.min(steps.length - 2, Math.floor(bounded));
      const cardProgress = bounded - cardFrom;
      const cardAmount = cardProgress * cardProgress * (3 - 2 * cardProgress);
      cards.forEach((card, i) => {
        const offset = i - cardFrom - cardAmount;
        const visible = moving
          ? Math.abs(offset) < 1
          : i === index;
        card.hidden = !visible;
        card.inert = i !== index;
        card.setAttribute('aria-hidden', String(i !== index));
        card.style.transform = moving
          ? `translateY(calc(-50% + ${offset * stage.clientHeight}px))` : '';
      });
      previous.disabled = index === 0;
      next.disabled = index === steps.length - 1;
      // Compact navigation follows the rendered playhead, not its destination.
      const progressChapter = !scrollLayout.matches
        ? MapStoryAnimation.chapterAt(position, timeline.stops) : bounded;
      // Grow only a reached stop; release it as the next overlay leg begins.
      const reachedStep = Math.floor(progressChapter);
      const activeDot = progressChapter - reachedStep < 0.5 ? reachedStep : -1;
      progress.style.setProperty('--progress', `${progressChapter / (steps.length - 1) * 100}%`);
      [...progress.children].forEach((dot, i) => {
        dot.classList.toggle('reached', i <= progressChapter);
        if (i === activeDot) dot.setAttribute('aria-current', 'step');
        else dot.removeAttribute('aria-current');
      });
    }
    // The map and card positions are pure samples of the same scroll timeline.
    const chapterDistance = () => (walkthrough.offsetHeight - stage.offsetHeight) / (steps.length - 1);
    let navigationFrame = null;
    let mapFrame = null;
    function cancelMapAnimation() {
      if (mapFrame !== null) cancelAnimationFrame(mapFrame);
      mapFrame = null;
    }
    const navigation = document.querySelector('.story-navigation');
    const mapZone = document.createElement('div');
    mapZone.className = 'map-zone';
    stage.append(mapZone);
    const focusElement = document.getElementById('focus-control');
    const mapControls = document.createElement('div');
    mapControls.className = 'map-controls';
    mapControls.append(map.zoomControl.getContainer(), focusElement);
    function cancelNavigation() {
      if (navigationFrame !== null) cancelAnimationFrame(navigationFrame);
      navigationFrame = null;
    }
    // User input always takes over from an arrow/dot's eased page movement.
    for (const event of ['wheel', 'touchstart', 'pointerdown', 'keydown']) {
      window.addEventListener(event, cancelNavigation, {passive: true});
    }
    function navigateStep(index) {
      if (index < 0 || index >= steps.length) return;
      cancelNavigation();
      cancelMapAnimation();
      if (!scrollLayout.matches && !reducedMotion.matches) {
        const start = lastPosition ?? timeline.stops[currentStep];
        const target = timeline.stops[index];
        const started = performance.now();
        renderChapter(index, start);
        function tickMap(now) {
          const t = Math.min(1, (now - started) / 1275);
          const eased = t * t * (3 - 2 * t);
          renderChapter(index, start + (target - start) * eased);
          mapFrame = t < 1 ? requestAnimationFrame(tickMap) : null;
        }
        mapFrame = requestAnimationFrame(tickMap);
        return;
      }
      if (scrollLayout.matches && !reducedMotion.matches) {
        const start = window.scrollY;
        const target = start + walkthrough.getBoundingClientRect().top + chapterDistance() * index + 1;
        const started = performance.now();
        function tick(now) {
          const t = Math.min(1, (now - started) / 1050);
          const eased = t * t * (3 - 2 * t);
          window.scrollTo({top: start + (target - start) * eased, behavior: 'instant'});
          syncScroll();
          navigationFrame = t < 1 ? requestAnimationFrame(tick) : null;
        }
        navigationFrame = requestAnimationFrame(tick);
        return;
      } else if (scrollLayout.matches) {
        window.scrollTo({top: window.scrollY + walkthrough.getBoundingClientRect().top
          + chapterDistance() * index + 1, behavior: 'instant'});
      }
      renderChapter(index);
    }
    previous.addEventListener('click', () => navigateStep(currentStep - 1));
    next.addEventListener('click', () => navigateStep(currentStep + 1));
    document.querySelector('.story-navigation-footer a').addEventListener('click', event => {
      event.preventDefault();
      cancelNavigation();
      const destination = document.getElementById('area-data');
      destination.focus({preventScroll: true});
      destination.scrollIntoView({behavior: reducedMotion.matches ? 'instant' : 'smooth', block: 'start'});
      history.replaceState(null, '', '#area-data');
    });
    let scrollFrame = null;
    function syncScroll() {
      scrollFrame = null;
      renderChapter(scrollLayout.matches
        ? -walkthrough.getBoundingClientRect().top / chapterDistance() : currentStep);
    }
    window.addEventListener('scroll', () => {
      if (scrollLayout.matches && scrollFrame === null) scrollFrame = requestAnimationFrame(syncScroll);
    }, {passive: true});
    function placeNavigation() {
      cancelNavigation();
      cancelMapAnimation();
      if (scrollLayout.matches) {
        stage.append(navigation);
        mapZone.append(mapControls);
      } else {
        cards[0].before(navigation);
        navigation.prepend(mapControls);
      }
      previous.textContent = scrollLayout.matches ? '↑' : '←';
      next.textContent = scrollLayout.matches ? '↓' : '→';
      syncScroll();
    }
    reducedMotion.addEventListener('change', () => { cancelNavigation(); cancelMapAnimation(); syncScroll(); });
    scrollLayout.addEventListener('change', placeNavigation);
    placeNavigation();
    renderChapter(0);
    const zoomIcon = path => `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="${path}"/></svg>`;
    map.zoomControl.getContainer().querySelector('.leaflet-control-zoom-in').innerHTML = zoomIcon('M5 12h14M12 5v14');
    map.zoomControl.getContainer().querySelector('.leaflet-control-zoom-out').innerHTML = zoomIcon('M5 12h14');
    const bounds = townLayer.getBounds();
    let focusRegion = null;
    const areaRpcs = new Map();
    for (const membership of mapData.memberships) {
      if (!areaRpcs.has(membership.feature_id)) areaRpcs.set(membership.feature_id, new Set());
      areaRpcs.get(membership.feature_id).add(townRpcs.get(membership.municipality_geoid));
    }
    const focusLayers = [];
    townLayer.eachLayer(layer => focusLayers.push({layer, matches: rpc => layer.feature.properties.focus_rpc === rpc}));
    areaLayer.eachLayer(layer => focusLayers.push({layer, matches: rpc => areaRpcs.get(layer.feature.properties.feature_id)?.has(rpc)}));
    tierLayer.eachLayer(layer => focusLayers.push({layer, matches: rpc => townRpcs.get(layer.feature.properties.geoid) === rpc}));
    housingLayers.forEach(({layer: collection}) => collection.eachLayer(layer => focusLayers.push({layer,
      matches: rpc => townRpcs.get(layer.feature.properties.geoid) === rpc})));
    rpcLayer.eachLayer(layer => focusLayers.push({layer, matches: rpc => layer.feature.properties.rpc === rpc}));
    const focusControl = document.getElementById('focus-control');
    const focusToggle = document.getElementById('focus-toggle');
    const focusOptions = document.getElementById('focus-options');
    const focusClear = document.getElementById('focus-clear');
    const focusName = feature => rpcName(feature.properties.rpc);
    function applyFocus({layer, matches}) {
      const element = layer.getElement();
      if (!element) return;
      element.classList.add('focus-overlay');
      element.classList.toggle('focus-overlay-hidden', !!focusRpc && !matches(focusRpc));
    }
    // Fade feature overlays independently of story fill/stroke animation and tiles.
    function selectFocus(feature, recenter = true) {
      focusRegion = feature;
      focusRpc = feature?.properties.rpc || null;
      cards.forEach((card, index) => card.querySelectorAll('.story-stat strong').forEach((value, stat) => {
        value.textContent = number(countStat(steps[index], steps[index].stats[stat].select));
      }));
      focusLayers.forEach(applyFocus);
      clearHover();
      document.getElementById('focus-name').textContent = feature ? focusName(feature) : 'Vermont';
      focusControl.classList.toggle('is-active', !!feature);
      focusClear.hidden = !feature;
      focusOptions.hidden = true;
      focusToggle.setAttribute('aria-expanded', 'false');
      focusOptions.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.rpc === (feature?.properties.rpc || ''))));
      if (recenter) fitVermont(true);
      focusToggle.focus({preventScroll: true});
    }
    for (const feature of [null, ...mapData.rpcs.features]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.rpc = feature?.properties.rpc || '';
      button.textContent = feature ? feature.properties.name : 'Vermont';
      button.setAttribute('aria-pressed', String(!feature));
      button.addEventListener('click', () => selectFocus(feature));
      focusOptions.append(button);
    }
    focusToggle.addEventListener('click', () => {
      focusOptions.hidden = !focusOptions.hidden;
      focusToggle.setAttribute('aria-expanded', String(!focusOptions.hidden));
      if (!focusOptions.hidden) focusOptions.querySelector('[aria-pressed="true"]').focus({preventScroll: true});
    });
    focusClear.addEventListener('click', () => selectFocus(null, false));
    document.getElementById('focus-recenter').addEventListener('click', () => fitVermont(true));
    focusControl.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        focusOptions.hidden = true;
        focusToggle.setAttribute('aria-expanded', 'false');
        focusToggle.focus({preventScroll: true});
      }
    });
    document.addEventListener('click', event => {
      if (!focusControl.contains(event.target)) {
        focusOptions.hidden = true;
        focusToggle.setAttribute('aria-expanded', 'false');
      }
    });
    function fitVermont(animate = false) {
      trackpad.finish();
      map.stop();
      map.invalidateSize();
      const zone = mapZone.getBoundingClientRect();
      const mapRect = map.getContainer().getBoundingClientRect();
      const padding = scrollLayout.matches ? {
        paddingTopLeft: [zone.left - mapRect.left + 24, zone.top - mapRect.top + 72],
        paddingBottomRight: [mapRect.right - zone.right + 24, mapRect.bottom - zone.bottom + 24],
      } : {};
      const targetBounds = focusRegion ? L.geoJSON(focusRegion).getBounds() : bounds;
      if (targetBounds.isValid()) {
        // Native movement retains tile levels during zoom. Per-frame setView
        // resets those levels and causes tile churn and visible blanking.
        map.fitBounds(targetBounds.pad(0.025), {
          ...padding, animate: animate && !reducedMotion.matches, duration: 0.45,
        });
      }
      else map.setView([44.04, -72.7], 7.25);
    }
    function resizeStory() {
      fitVermont();
      if (mapFrame === null) syncScroll();
    }
    new ResizeObserver(resizeStory).observe(document.getElementById('map'));
    resizeStory();
    // Leaflet creates a new SVG path on each add; restore focus classes then too.
    focusLayers.forEach(item => {
      item.layer.on('add', () => applyFocus(item));
      applyFocus(item);
    });
  }
  initMap();

  function render() {
    const query = search.value.trim().toLocaleLowerCase();
    const groups = data.municipalities.map(group => ({...group, areas: group.areas.filter(area => {
      const searchable = `${group.municipality} ${area.name} ${area.exemption_type || ''} ${area.category_label}`.toLocaleLowerCase();
      return (!query || searchable.includes(query)) &&
        (eligibility.value === 'all' || status(area.likely_eligible) === eligibility.value) &&
        (category.value === 'all' || area.category === category.value);
    })})).filter(group => group.areas.length);
    const areas = groups.flatMap(group => group.areas);
    for (const body of [...table.tBodies]) body.remove();
    const fragment = document.createDocumentFragment();
    for (const group of groups) {
      const body = document.createElement('tbody');
      for (const [index, area] of group.areas.entries()) {
        const row = document.createElement('tr');
        row.dataset.featureId = area.feature_id;
        if (index === 0) {
          const town = document.createElement('th');
          town.scope = 'rowgroup';
          town.rowSpan = group.areas.length;
          town.className = 'municipality';
          town.append(document.createTextNode(displayMunicipality(group.municipality)));
          const count = document.createElement('small');
          count.textContent = `${group.areas.length} ${group.areas.length === 1 ? 'area' : 'areas'}`;
          town.append(count);
          row.append(town);
        }
        const label = document.createElement('td');
        label.className = 'area';
        const name = document.createElement('span');
        name.className = 'area-name';
        name.textContent = area.name === area.name.toUpperCase() ? displayMunicipality(area.name) : area.name;
        const type = document.createElement('span');
        type.className = 'area-type';
        type.textContent = area.exemption_type || area.category_label;
        label.append(name, type);
        row.append(label);
        fields.forEach((field, index) => {
          const cell = document.createElement('td');
          const state = status(area[field]);
          cell.className = `boolean ${state}${index === 0 ? ' eligibility' : ''}`;
          cell.textContent = state === 'yes' ? 'Yes' : state === 'no' ? 'No' : 'Unknown';
          if (field === 'zoning_bylaws') {
            cell.textContent = state === 'yes' ? 'Met' : state === 'no' ? 'Not met' : 'Unknown';
          }
          if (field === 'zoning_bylaws' && !EligibilityDisplay.zoningApplies(area)) {
            cell.className = 'boolean not-required';
            cell.textContent = 'Not separately required';
            cell.title = 'Not a separate condition in the town/growth/development exemption clause; source zoning value remains unreported.';
          }
          row.append(cell);
        });
        const infrastructure = document.createElement('td');
        infrastructure.className = 'infrastructure-cell';
        const infrastructureState = status(EligibilityDisplay.infrastructure(area));
        const result = document.createElement('strong');
        result.className = `requirement-result ${infrastructureState}`;
        result.textContent = infrastructureState === 'yes' ? '✓ Met' : infrastructureState === 'no' ? '✕ Not met' : '? Unknown';
        const alternatives = document.createElement('div');
        alternatives.className = 'infrastructure-alternatives';
        for (const [field, label] of [['drinking_water', 'Water'], ['sewer_wastewater', 'Wastewater'], ['adequate_soils', 'Soils']]) {
          const item = document.createElement('span');
          const state = status(area[field]);
          item.className = `alternative alternative-${state}`;
          item.textContent = `${state === 'yes' ? '✓' : state === 'no' ? '✕' : '?'} ${label}`;
          item.setAttribute('aria-label', `${label}: ${state === 'yes' ? 'Yes' : state === 'no' ? 'No' : 'Unknown'}`);
          item.title = item.getAttribute('aria-label');
          alternatives.append(item);
        }
        infrastructure.append(result, alternatives);
        row.append(infrastructure);
        body.append(row);
      }
      fragment.append(body);
    }
    table.append(fragment);
    document.getElementById('empty').hidden = areas.length !== 0;
    document.getElementById('area-count').textContent = number(areas.length);
    document.getElementById('municipality-count').textContent = number(groups.length);
    document.getElementById('yes-count').textContent = number(areas.filter(a => a.likely_eligible === true).length);
    document.getElementById('no-count').textContent = number(areas.filter(a => a.likely_eligible === false).length);
    const unknown = areas.filter(a => a.likely_eligible == null).length;
    document.getElementById('results').textContent = `Showing ${number(areas.length)} of ${number(data.summary.areas)} areas · ${number(groups.length)} municipality groups${unknown ? ` · ${unknown} eligibility unknown` : ''}`;
  }
  search.addEventListener('input', render);
  eligibility.addEventListener('change', render);
  category.addEventListener('change', render);
  document.getElementById('filters').addEventListener('submit', event => event.preventDefault());
  document.getElementById('filters').addEventListener('reset', () => {
    search.value = ''; eligibility.value = 'all'; category.value = 'all'; render();
  });
  render();
})();
