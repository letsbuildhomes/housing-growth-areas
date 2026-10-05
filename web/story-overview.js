// Starting point for the next research journey, using only existing saved data.
window.MapStories.register({
  id: 'saved-map-overview', enabled: true,
  create({tierData, colors, areaColor}) {
    const {positive, unknown} = colors;
    const tierTowns = new Set(tierData.areas.features.map(f => f.properties.geoid));
    return {
      steps: [
        {title: 'Vermont’s saved maps',
          description: 'Explore the saved boundaries of Vermont’s municipalities, temporary exemption areas, and Tier 1B mapping.',
          stats: [{select: () => true, label: 'Municipalities', color: unknown}], areaKey: []},
        {title: 'Temporary exemption areas',
          description: 'These designated areas carry the publisher’s likely interim Act 250 exemption eligibility. A municipality’s count does not mean its entire territory is exempt.',
          stats: [{select: p => p.has_likely_eligible, label: 'With likely eligible areas', color: positive}],
          areaKey: [[positive, 'Likely eligible'], [colors.negative, 'Likely not eligible'], [unknown, 'Unknown']]},
        {title: 'Tier 1B mapping',
          description: 'Each region shows its furthest populated map stage in the saved snapshot. Hover over a polygon to see its stage; mapped areas are not all approved.',
          stats: [{select: p => tierTowns.has(p.geoid), label: 'With mapped Tier 1B areas', color: positive}],
          areaKey: [[positive, 'Tier 1B boundaries']]},
      ],
      groups: [
        [item => item.kind === 'area' ? {color: areaColor(item.props.likely_eligible),
          fillColor: areaColor(item.props.likely_eligible), opacity: 1, fillOpacity: 0.75}
          : item.kind === 'town' ? {fillColor: positive, fillOpacity: item.props.has_likely_eligible ? 0.6 : 0} : {}],
        [item => item.kind === 'area' ? {opacity: 0, fillOpacity: 0}
          : item.kind === 'tier' ? {opacity: 0.9, fillOpacity: 0.6}
          : item.kind === 'town' ? {fillColor: positive, fillOpacity: tierTowns.has(item.props.geoid) ? 0.6 : 0} : {}],
      ],
    };
  },
});
