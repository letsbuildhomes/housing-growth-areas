// Housing Growth Areas and their representation in the selected Tier 1B map.
window.MapStories.register({
  id: 'saved-map-overview', enabled: true,
  create({housingData, mapData, colors}) {
    const summaries = new Map(housingData.municipalities.map(p => [p.geoid, p]));
    const townStatus = p => summaries.get(p.geoid)?.status || 'unknown';
    const municipalColors = {all: colors.gain, some: colors.partial, none: colors.negative,
      no_housing: colors.neutral, unknown: colors.unknown};
    const coverageColors = {covered: colors.gain, uncovered: colors.negative, unknown: colors.unknown};
    const categoryColors = {VA: colors.villageArea, VC: colors.villageCenter,
      PGA: colors.plannedGrowth, DC: colors.downtown};
    const hasGrowth = p => (summaries.get(p.geoid)?.block_count || 0) > 0;
    const noGrowth = p => summaries.get(p.geoid)?.status === 'no_housing';
    const unknownGrowth = p => !hasGrowth(p) && !noGrowth(p);
    const hasUnknownGrowth = housingData.municipalities.some(unknownGrowth) ||
      (mapData?.towns?.features || []).some(f => !summaries.has(f.properties.geoid));
    const hasUnknownTowns = housingData.municipalities.some(p => p.status === 'unknown') ||
      (mapData?.towns?.features || []).some(f => !summaries.has(f.properties.geoid));
    const hasUnknownCoverage = (housingData.coverage_parts?.features || []).some(f => f.properties.coverage_kind === 'unknown');
    const hasUnknownBlocks = (housingData.blocks?.features || []).some(f => f.properties.coverage_status === 'unknown');
    const coverageKey = [[colors.gain, 'Mapped as Tier 1B'], [colors.negative, 'Not mapped as Tier 1B'],
      ...(hasUnknownCoverage ? [[colors.unknown, 'Cannot assess']] : [])];
    return {
      overlays: ['housing-category', 'housing-block', 'housing-coverage'],
      initial: item => item.kind === 'housing-category'
        ? {color: categoryColors[item.props.flu_code], fillColor: categoryColors[item.props.flu_code], opacity: 0.95, fillOpacity: 0.8}
        : {},
      steps: [
        {title: 'Housing Growth Areas', municipalityView: 'growth',
          description: 'Housing Growth Areas are the places regional future land use maps designate as a Downtown Center, Village Center, Planned Growth Area, or Village Area.',
          statsOf: 'areas', statsTitle: 'Housing Growth Areas',
          stats: [{select: () => true, label: 'Mapped Housing Growth Areas'}],
          areaKey: [[colors.villageArea, 'Village Area'], [colors.villageCenter, 'Village Center'],
            [colors.plannedGrowth, 'Planned Growth Area'], [colors.downtown, 'Downtown Center']]},
        {title: 'Municipalities with Housing Growth Areas', municipalityView: 'growth', municipalFill: true,
          description: 'Green municipalities have at least one Housing Growth Area. Red municipalities have none.',
          stats: [{select: hasGrowth, label: 'With Housing Growth Areas', color: colors.gain},
            {select: noGrowth, label: 'No Housing Growth Areas', color: colors.negative},
            ...(hasUnknownGrowth ? [{select: unknownGrowth, label: 'Cannot assess Housing Growth Areas', color: colors.unknown}] : [])],
          areaKey: [[colors.positive, 'Housing Growth Areas']]},
        {title: 'Not every Housing Growth Area is Tier 1B', municipalityView: 'coverage',
          description: 'Green marks the parts of Housing Growth Areas on track for Tier 1B. Red marks the parts being left behind. Not every Tier 1B map is approved yet; hover for each submission stage.',
          statsOf: 'areas', statsTitle: 'Housing Growth Areas',
          stats: [['substantial', 'Mapped as Tier 1B'], ['partial', 'Partly mapped as Tier 1B'], ['none', 'Not mapped as Tier 1B'],
            ...(hasUnknownBlocks ? [['unknown', 'Cannot assess']] : [])]
            .map(([state, label]) => ({select: b => b.coverage_status === state, label})),
          areaKey: coverageKey},
        {title: 'Tier 1B designation by municipality', municipalityView: 'coverage', municipalFill: true,
          description: 'Green municipalities have Tier 1B across all of their Housing Growth Areas, yellow across some, and red across none. Gray municipalities have no Housing Growth Areas.',
          stats: [['all', 'Full Tier 1B designation'], ['some', 'Partial Tier 1B designation'], ['none', 'No Tier 1B designation'],
            ['no_housing', 'No Housing Growth Areas'], ...(hasUnknownTowns ? [['unknown', 'Cannot assess']] : [])]
            .map(([state, label]) => ({select: p => townStatus(p) === state, label, color: municipalColors[state]})),
          areaKey: coverageKey},
      ],
      groups: [
        [item => item.kind === 'town' ? {fillColor: hasGrowth(item.props) ? colors.gain
            : noGrowth(item.props) ? colors.negative : colors.unknown, fillOpacity: 0.55}
          : item.kind === 'housing-category' ? {color: colors.positive, fillColor: colors.positive,
            opacity: 0.75, fillOpacity: 0.35} : {}],
        [item => item.kind === 'housing-category' ? {opacity: 0, fillOpacity: 0}
          : item.kind === 'town' ? {fillOpacity: 0}
          : item.kind === 'housing-coverage' ? {color: coverageColors[item.props.coverage_kind],
            fillColor: coverageColors[item.props.coverage_kind], opacity: 0.95, fillOpacity: 0.8} : {}],
        [item => item.kind === 'town' ? {fillColor: municipalColors[townStatus(item.props)], fillOpacity: 0.55}
          : item.kind === 'housing-coverage' ? {fillOpacity: 0.9} : {}],
      ],
    };
  },
});
