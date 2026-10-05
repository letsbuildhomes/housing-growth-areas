(async () => {
  'use strict';
  const loadStatus = document.getElementById('data-status');
  let data, mapData, tierData;
  try {
    [data, mapData, tierData] = await Promise.all(['interim-areas.json', 'map.json', 'tier1b.json'].map(async name => {
      const response = await fetch(`./data/${name}`);
      if (!response.ok) throw new Error(`Could not load ${name}: HTTP ${response.status}`);
      return response.json();
    }));
    if (data.schema_version !== 1 || mapData.schema_version !== 2 || tierData.schema_version !== 3 ||
        ['snapshot_id', 'captured_at', 'exported_at'].some(key => !data[key] || data[key] !== mapData[key] || data[key] !== tierData[key])) {
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
    const map = L.map('map', {zoomControl: true, scrollWheelZoom: false, fadeAnimation: false,
      zoomSnap: 0.25, zoomDelta: 0.5, minZoom: 6, maxZoom: 19});
    map.attributionControl.setPrefix(false);
    const basemapStatus = document.getElementById('basemap-status');
    const basemap = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    });
    basemap.on('tileerror', () => { basemapStatus.hidden = false; });
    basemap.on('loading', () => { basemapStatus.hidden = true; });
    basemap.addTo(map);
    const townLayer = L.geoJSON(mapData.towns, {
      interactive: false,
      style: feature => ({color: '#536c70', weight: 1, opacity: 0.85,
        fillColor: '#788992', fillOpacity: 0}),
    }).addTo(map);
    map.createPane('rpcBoundaries');
    map.getPane('rpcBoundaries').style.zIndex = 450;
    map.getPane('rpcBoundaries').style.pointerEvents = 'none';
    const rpcLayer = L.geoJSON(mapData.rpcs, {
      pane: 'rpcBoundaries', interactive: false,
      style: {color: themeColor('--brand-green'), weight: 1.6, opacity: 0.8, fill: false},
    }).addTo(map);
    map.createPane('storyAreas');
    map.getPane('storyAreas').style.zIndex = 440;
    const areaLayer = L.geoJSON(mapData.areas, {
      pane: 'storyAreas',
      style: feature => ({color: areaColor(feature.properties.likely_eligible), weight: 1.2,
        opacity: 0.9, fillColor: areaColor(feature.properties.likely_eligible), fillOpacity: 0.42}),
      onEachFeature: (feature, layer) => {
        layer.bindTooltip(() => areaTooltip(feature.properties), {
          sticky: true, opacity: 1, className: 'area-hover', direction: 'auto',
        });
      }
    }).addTo(map);
    const {positive: good, negative: bad, unknown: muted, absent} = mapColors;
    const gain = themeColor('--map-gain');
    const tierColor = good;
    const tierLabels = {pre_application: 'Pre-application', application: 'Application', approved: 'Approved'};
    const tierPane = map.createPane('tierWorking');
    tierPane.style.zIndex = 430;
    const tierLayer = L.geoJSON(tierData.areas, {
      pane: 'tierWorking',
      style: {color: tierColor, fillColor: tierColor, weight: 1.2, opacity: 0, fillOpacity: 0},
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        layer.bindTooltip(() => `<strong class="area-hover-name">Tier 1B · ${escapeHTML(tierLabels[p.map_stage])}</strong>
          <div class="area-hover-town">${escapeHTML(p.municipality)} · ${escapeHTML(p.rpc || 'Unknown RPC')} RPC</div>
          ${p.name ? `<div class="area-hover-type">${escapeHTML(p.name)}</div>` : ''}`, {
          sticky: true, opacity: 1, className: 'area-hover', direction: 'auto',
        });
      },
    }).addTo(map);
    let focusRpc = null;
    const countTowns = predicate => mapData.towns.features.filter(f =>
      (!focusRpc || f.properties.focus_rpc === focusRpc) && predicate(f.properties)).length;
    const {steps, groups} = MapStories.create({mapData, tierData,
      colors: {...mapColors, gain}, areaColor});
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const initial = [];
    townLayer.eachLayer(layer => initial.push({layer, kind: 'town', props: layer.feature.properties,
      style: {fillColor: layer.feature.properties.has_designated_area ? good : absent, fillOpacity: 0}}));
    areaLayer.eachLayer(layer => initial.push({layer, kind: 'area', props: layer.feature.properties,
      style: {color: good, fillColor: good, opacity: 0, fillOpacity: 0}}));
    tierLayer.eachLayer(layer => initial.push({layer, kind: 'tier',
      props: layer.feature.properties, style: {opacity: 0, fillOpacity: 0}}));
    const timeline = MapStoryAnimation.compile(initial, groups);
    let currentStep = 0, lastPosition = null;
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
        </div><div class="story-key"><h4>Municipalities · map key</h4>
        <div class="story-stats">${step.stats.map(({select, label, color}) =>
          `<div class="story-stat" style="--stat-color:${color}"><i class="stat-swatch" aria-hidden="true"></i><strong>${number(countTowns(select))}</strong><span>${escapeHTML(label)}</span></div>`).join('')}</div>
        ${step.areaKey.length ? `<div class="story-area-key"><h4>Area polygons</h4><div>${step.areaKey.map(([color, label]) =>
          `<span><i style="background:${color}" aria-hidden="true"></i>${escapeHTML(label)}</span>`).join('')}</div></div>` : ''}
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
        areaLayer.eachLayer(layer => layer.closeTooltip());
        tierLayer.eachLayer(layer => layer.closeTooltip());
      }
      currentStep = index;
      const position = reducedMotion.matches ? timeline.stops[index] : (mapPosition ?? state.position);
      if (position !== lastPosition) {
        timeline.sample(position).forEach(item => {
          item.layer.setStyle(item.style);
          if (item.kind !== 'town') {
            item.layer.getElement()?.classList.toggle('story-area-hidden', item.style.opacity === 0);
            if (item.style.opacity === 0) item.layer.closeTooltip();
          }
        });
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
    const townRpcs = new Map(mapData.towns.features.map(f => [f.properties.geoid, f.properties.focus_rpc]));
    const areaRpcs = new Map();
    for (const membership of mapData.memberships) {
      if (!areaRpcs.has(membership.feature_id)) areaRpcs.set(membership.feature_id, new Set());
      areaRpcs.get(membership.feature_id).add(townRpcs.get(membership.municipality_geoid));
    }
    const focusLayers = [];
    townLayer.eachLayer(layer => focusLayers.push({layer, matches: rpc => layer.feature.properties.focus_rpc === rpc}));
    areaLayer.eachLayer(layer => focusLayers.push({layer, matches: rpc => areaRpcs.get(layer.feature.properties.feature_id)?.has(rpc)}));
    tierLayer.eachLayer(layer => focusLayers.push({layer, matches: rpc => townRpcs.get(layer.feature.properties.geoid) === rpc}));
    rpcLayer.eachLayer(layer => focusLayers.push({layer, matches: rpc => layer.feature.properties.rpc === rpc}));
    const focusControl = document.getElementById('focus-control');
    const focusToggle = document.getElementById('focus-toggle');
    const focusOptions = document.getElementById('focus-options');
    const focusClear = document.getElementById('focus-clear');
    const rpcNames = {AC: 'ACRPC', BC: 'BCRC', CV: 'CVRPC', CC: 'CCRPC',
      LC: 'LCPC', MA: 'MARC', NV: 'NVDA', NW: 'NRPC', RR: 'RRPC', TR: 'TRORC', WR: 'WRC'};
    const focusName = feature => rpcNames[feature.properties.rpc] || feature.properties.rpc;
    // Fade feature overlays independently of story fill/stroke animation and tiles.
    function selectFocus(feature, recenter = true) {
      focusRegion = feature;
      focusRpc = feature?.properties.rpc || null;
      cards.forEach((card, index) => card.querySelectorAll('.story-stat strong').forEach((value, stat) => {
        value.textContent = number(countTowns(steps[index].stats[stat].select));
      }));
      focusLayers.forEach(({layer, matches}) => {
        layer.getElement()?.classList.toggle('focus-overlay-hidden', !!focusRpc && !matches(focusRpc));
      });
      areaLayer.eachLayer(layer => layer.closeTooltip());
      tierLayer.eachLayer(layer => layer.closeTooltip());
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
    focusLayers.forEach(({layer}) => layer.getElement()?.classList.add('focus-overlay'));
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
