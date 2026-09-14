(async () => {
  'use strict';
  const loadStatus = document.getElementById('data-status');
  let data, mapData;
  try {
    [data, mapData] = await Promise.all(['interim-areas.json', 'map.json'].map(async name => {
      const response = await fetch(`./data/${name}`);
      if (!response.ok) throw new Error(`Could not load ${name}: HTTP ${response.status}`);
      return response.json();
    }));
    if (data.schema_version !== 1 || mapData.schema_version !== 2 ||
        ['snapshot_id', 'captured_at', 'exported_at'].some(key => !data[key] || data[key] !== mapData[key])) {
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
    const determination = state === 'yes' ? 'Likely Exempt' : state === 'no' ? 'Likely Not Exempt' : 'Exemption Unknown';
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
    const map = L.map('map', {zoomControl: true, scrollWheelZoom: false,
      zoomSnap: 0.25, minZoom: 6, maxZoom: 19});
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
    const total = mapData.summary.municipalities;
    const designated = mapData.summary.towns_with_designated_area;
    const eligible = mapData.summary.towns_with_likely_eligible_area;
    // Chapter copy is separate from the phase groups that lead into each chapter.
    const steps = [
      {title: "Act 181",
        description: 'Act 181 aimed to give Vermont\'s cities and towns relief from Act 250 to help spur housing development in designated areas. How has this process panned out?',
        stats: [{count: total, label: 'Municipalities', color: muted}],
        areaKey: [],
      },
      {title: 'Designated areas',
        description: 'Some municipalities contain designated areas; others have none. Act 181 uses these areas as the basis for temporary Act 250 exemption.',
        stats: [{count: designated, label: 'With areas', color: good},
          {count: total - designated, label: 'No areas', color: absent}],
        areaKey: [[good, 'Designated areas']],
      },
      {title: 'Likely exemptions',
        description: 'Not all areas are exempt: there are infrastructure and zoning requirements for temporary exemptions.',
        stats: [{count: eligible, label: 'Likely eligible area', color: good},
          {count: designated - eligible, label: 'No likely eligible area', color: bad},
          {count: total - designated, label: 'No designated areas', color: absent}],
        areaKey: [[good, 'Likely eligible'], [bad, 'Likely ineligible'], [muted, 'Unknown']],
      },
    ];
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    // A phase changes only its selected features. Reverse playback traverses
    // these same phases and gaps in reverse, including partially played phases.
    const phase = (kind, select, style) => item => item.kind === kind && select(item.props)
      ? (typeof style === 'function' ? style(item.props) : style) : {};
    const groups = [
      [ // Boundaries → designated areas
        phase('area', () => true, {opacity: 1, fillOpacity: 0.75}),
        phase('town', p => p.has_designated_area, {fillColor: good, fillOpacity: 0.6}),
        phase('town', p => !p.has_designated_area, {fillColor: absent, fillOpacity: 0.6}),
      ],
      [ // Designated areas → likely exemption eligibility
        phase('area', p => p.likely_eligible !== true, p => ({color: areaColor(p.likely_eligible), fillColor: areaColor(p.likely_eligible)})),
        phase('town', p => p.has_designated_area && !p.has_likely_eligible, {fillColor: bad}),
      ],
    ];
    const initial = [];
    townLayer.eachLayer(layer => initial.push({layer, kind: 'town', props: layer.feature.properties,
      style: {fillColor: layer.feature.properties.has_designated_area ? good : absent, fillOpacity: 0}}));
    areaLayer.eachLayer(layer => initial.push({layer, kind: 'area', props: layer.feature.properties,
      style: {color: good, fillColor: good, opacity: 0, fillOpacity: 0}}));
    const timeline = MapStoryAnimation.compile(initial, groups);
    let currentStep = 0, lastPosition = null;
    const scrollLayout = window.matchMedia('(min-width: 1000px) and (min-height: 700px)');
    const walkthrough = document.getElementById('map-walkthrough');
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
        <div class="story-stats">${step.stats.map(({count, label, color}) =>
          `<div class="story-stat" style="--stat-color:${color}"><i class="stat-swatch" aria-hidden="true"></i><strong>${number(count)}</strong><span>${escapeHTML(label)}</span></div>`).join('')}</div>
        ${step.areaKey.length ? `<div class="story-area-key"><h4>Area polygons</h4><div>${step.areaKey.map(([color, label]) =>
          `<span><i style="background:${color}" aria-hidden="true"></i>${escapeHTML(label)}</span>`).join('')}</div></div>` : ''}
        </div></div>`;
      originalCard.before(card);
      return card;
    });
    originalCard.remove();
    progress.innerHTML = steps.map((step, index) => `<button type="button" class="story-stop"
      style="left:${index / (steps.length - 1) * 100}%" aria-label="${escapeHTML(step.title)}" title="${escapeHTML(step.title)}"></button>`).join('');
    [...progress.children].forEach((dot, index) => dot.addEventListener('click', () => navigateStep(index)));
    function renderChapter(chapter, mapPosition) {
      const bounded = Math.max(0, Math.min(steps.length - 1, chapter));
      const state = MapStoryAnimation.scrollState(bounded, timeline.stops);
      const index = Math.round(bounded);
      if (index !== currentStep) areaLayer.eachLayer(layer => layer.closeTooltip());
      currentStep = index;
      const position = reducedMotion.matches ? timeline.stops[index] : (mapPosition ?? state.position);
      if (position !== lastPosition) {
        timeline.sample(position).forEach(item => item.layer.setStyle(item.style));
        map.getPane('storyAreas').classList.toggle('story-areas-hidden', position === 0);
        lastPosition = position;
      }
      const moving = scrollLayout.matches && !reducedMotion.matches;
      cards.forEach((card, i) => {
        const offset = i <= state.from ? -state.amount : 1 - state.amount;
        const visible = moving
          ? (i === state.from && state.amount < 1) || (i === state.from + 1 && state.amount > 0)
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
      const activeDot = !scrollLayout.matches ? Math.floor(progressChapter) : index;
      progress.style.setProperty('--progress', `${progressChapter / (steps.length - 1) * 100}%`);
      [...progress.children].forEach((dot, i) => {
        dot.classList.toggle('reached', i <= progressChapter);
        if (i === activeDot) dot.setAttribute('aria-current', 'step');
        else dot.removeAttribute('aria-current');
      });
    }
    // The map and card positions are pure samples of the same scroll timeline.
    const chapterDistance = () => (walkthrough.offsetHeight - stage.offsetHeight) / steps.length;
    let navigationFrame = null;
    let mapFrame = null;
    function cancelMapAnimation() {
      if (mapFrame !== null) cancelAnimationFrame(mapFrame);
      mapFrame = null;
    }
    const navigation = document.querySelector('.story-navigation');
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
      if (scrollLayout.matches) stage.append(navigation);
      else cards[0].before(navigation);
      syncScroll();
    }
    reducedMotion.addEventListener('change', () => { cancelNavigation(); cancelMapAnimation(); syncScroll(); });
    scrollLayout.addEventListener('change', placeNavigation);
    placeNavigation();
    renderChapter(0);
    map.zoomControl.setPosition('bottomright');
    const actions = L.control({position: 'bottomright'});
    actions.onAdd = () => {
      const element = document.querySelector('.map-actions');
      L.DomEvent.disableClickPropagation(element);
      return element;
    };
    actions.addTo(map);
    document.getElementById('rpc-toggle').addEventListener('change', event => {
      if (event.target.checked) rpcLayer.addTo(map);
      else map.removeLayer(rpcLayer);
    });
    const bounds = townLayer.getBounds();
    function fitVermont() {
      map.invalidateSize();
      const padding = scrollLayout.matches ? {paddingTopLeft: [60, 35], paddingBottomRight: [352 + stage.clientWidth * .08 + 24, 140]} : {};
      if (bounds.isValid()) map.fitBounds(bounds.pad(0.025), {...padding, animate: false});
      else map.setView([44.04, -72.7], 7.25);
    }
    function resizeStory() {
      fitVermont();
      if (mapFrame === null) syncScroll();
    }
    document.getElementById('map-reset').addEventListener('click', fitVermont);
    new ResizeObserver(resizeStory).observe(document.getElementById('map'));
    resizeStory();
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
