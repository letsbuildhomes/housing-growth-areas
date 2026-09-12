(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('interim-data').textContent);
  const mapData = JSON.parse(document.getElementById('map-data').textContent);
  const table = document.getElementById('areas-table');
  const search = document.getElementById('search');
  const eligibility = document.getElementById('eligibility');
  const category = document.getElementById('category');
  const fields = ['likely_eligible', 'zoning_bylaws', 'drinking_water', 'sewer_wastewater', 'adequate_soils'];
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
  const areaColor = value => value === true ? '#3b88b5' : value === false ? '#c45a5d' : '#788992';
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
    return `<strong class="area-hover-name">${escapeHTML(props.name || props.category || 'Interim area')}</strong>
      <div class="area-hover-town">${escapeHTML(displayMunicipality(props.municipality || 'Unknown municipality'))}</div>
      <div class="area-hover-status ${state}">${determination}</div>
      <table class="area-hover-criteria" aria-label="Reported eligibility criteria"><tbody>${criteria.map(([field, label]) => {
        const value = status(details[field]);
        return `<tr><th scope="row">${label}</th><td class="${value}">${value === 'yes' ? 'Yes' : value === 'no' ? 'No' : 'Unknown'}</td></tr>`;
      }).join('')}</tbody></table>`;
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
      style: feature => ({color: '#8297a3', weight: 0.65, opacity: 0.62,
        fillColor: '#788992', fillOpacity: 0}),
    }).addTo(map);
    map.createPane('rpcBoundaries');
    map.getPane('rpcBoundaries').style.zIndex = 450;
    map.getPane('rpcBoundaries').style.pointerEvents = 'none';
    const rpcLayer = L.geoJSON(mapData.rpcs, {
      pane: 'rpcBoundaries', interactive: false,
      style: {color: '#344d5b', weight: 1.6, opacity: 0.8, fill: false},
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
    const good = '#3b88b5', bad = '#c45a5d', muted = '#788992', absent = '#a18e78';
    const total = mapData.summary.municipalities;
    const designated = mapData.summary.towns_with_designated_area;
    const eligible = mapData.summary.towns_with_likely_eligible_area;
    // Chapter copy is separate from the phase groups that lead into each chapter.
    const steps = [
      {title: 'Vermont, town by town',
        description: 'Start with the municipal boundaries that frame this story.',
        stats: [{count: total, label: 'Municipalities', color: muted}],
        areaKey: [],
      },
      {title: 'Designated areas',
        description: 'Some municipalities contain designated areas; others have none.',
        stats: [{count: designated, label: 'With areas', color: good},
          {count: total - designated, label: 'No areas', color: absent}],
        areaKey: [[good, 'Designated areas']],
      },
      {title: 'Likely exemptions',
        description: 'Which municipalities have an area with likely interim Act 250 exemption eligibility?',
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
    const playback = MapStoryAnimation.player(timeline, (items, position) => {
      items.forEach(item => item.layer.setStyle(item.style));
      map.getPane('storyAreas').classList.toggle('story-areas-hidden', position === 0);
    }, {reduced: () => reducedMotion.matches});
    let currentStep = 0;
    const previous = document.getElementById('story-prev');
    const next = document.getElementById('story-next');
    const progress = document.getElementById('story-progress');
    progress.innerHTML = steps.map(() => '<span></span>').join('');
    function showStep(index) {
      if (index < 0 || index >= steps.length) return;
      currentStep = index;
      const step = steps[index];
      areaLayer.eachLayer(layer => layer.closeTooltip());
      document.getElementById('story-position').textContent = `Step ${index + 1} of ${steps.length}`;
      document.getElementById('story-title').textContent = step.title;
      document.getElementById('story-description').textContent = step.description;
      document.getElementById('map-legend').innerHTML = step.stats.map(({count, label, color}) =>
        `<div class="story-stat" style="--stat-color:${color}"><i class="stat-swatch" aria-hidden="true"></i><strong>${number(count)}</strong><span>${escapeHTML(label)}</span></div>`).join('');
      const areaKey = document.getElementById('story-area-key');
      areaKey.hidden = !step.areaKey.length;
      areaKey.innerHTML = step.areaKey.length ? `<h4>Area polygons</h4><div>${step.areaKey.map(([color, label]) =>
        `<span><i style="background:${color}" aria-hidden="true"></i>${escapeHTML(label)}</span>`).join('')}</div>` : '';
      previous.disabled = index === 0;
      next.disabled = index === steps.length - 1;
      [...progress.children].forEach((dot, i) => dot.classList.toggle('active', i === index));
      playback.go(index);
    }
    previous.addEventListener('click', () => showStep(currentStep - 1));
    next.addEventListener('click', () => showStep(currentStep + 1));
    reducedMotion.addEventListener('change', () => playback.go(currentStep));
    showStep(0);
    document.getElementById('rpc-toggle').addEventListener('change', event => {
      if (event.target.checked) rpcLayer.addTo(map);
      else map.removeLayer(rpcLayer);
    });
    const bounds = townLayer.getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.025));
    else map.setView([44.04, -72.7], 7.25);
    document.getElementById('map-reset').addEventListener('click', () => {
      if (bounds.isValid()) map.fitBounds(bounds.pad(0.025));
    });
    document.getElementById('map-summary').textContent = `${number(mapData.summary.areas)} areas · ${number(mapData.summary.municipalities)} towns · ${number(mapData.summary.rpcs)} RPCs`;
    window.setTimeout(() => map.invalidateSize(), 0);
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
          row.append(cell);
        });
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
