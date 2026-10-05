// Preserved original journey. Copy and phases belong to this story, not the map controller.
window.MapStories.register({
  id: 'act181', enabled: false,
  create({mapData, tierData, colors, areaColor}) {
    const {positive: good, negative: bad, unknown: muted, absent, gain} = colors;
    const tierColor = good;
    const tierTownIds = new Set(tierData.areas.features.map(f => f.properties.geoid));
    const hasTier = p => tierTownIds.has(p.geoid);
    const gainedTier = p => !p.has_likely_eligible && hasTier(p);
    const lostTier = p => p.has_likely_eligible && !hasTier(p);
    const replacedAreaIds = new Set(mapData.memberships.filter(m => tierTownIds.has(m.municipality_geoid)).map(m => m.feature_id));
    const remainingExempt = p => p.likely_eligible === true && !replacedAreaIds.has(p.feature_id);
    // Chapter copy is separate from the phase groups that lead into each chapter.
    const steps = [
      {title: "Act 181",
        description: 'Act 181 aimed to give Vermont\'s cities and towns relief from Act 250 to help spur housing development in designated areas. How has this process panned out?',
        stats: [{select: () => true, label: 'Municipalities', color: muted}],
        areaKey: [],
      },
      {title: 'Designated areas',
        description: 'Some municipalities contain designated areas; others have none. Act 181 uses these areas as the basis for temporary Act 250 exemption.',
        stats: [{select: p => p.has_designated_area, label: 'With areas', color: gain},
          {select: p => !p.has_designated_area, label: 'No areas', color: bad}],
        areaKey: [[good, 'Designated areas']],
      },
      {title: 'Temporary exemptions',
        description: 'Not all areas are exempt: there are infrastructure and zoning requirements for temporary exemptions.',
        stats: [{select: p => p.has_likely_eligible, label: 'Has temporary exemptions', color: good},
          {select: p => p.has_designated_area && !p.has_likely_eligible, label: 'No temporary exemptions', color: bad},
          {select: p => !p.has_designated_area, label: 'No designated areas', color: absent}],
        areaKey: [[good, 'Exempt'], [bad, 'Not exempt'], [muted, 'Unknown']],
      },
      {title: 'Tier 1B boundaries',
        description: 'Each region shows its furthest completed mapping stage in the saved snapshot. Hover over a Tier 1B area to see whether it is pre-application, application, or approved.',
        stats: [{select: p => p.has_likely_eligible && hasTier(p), label: 'Both', color: good},
          {select: gainedTier, label: 'Tier 1B only', color: gain},
          {select: lostTier, label: 'Temporary exemptions only', color: good},
          {select: p => !p.has_likely_eligible && !hasTier(p), label: 'Neither', color: absent}],
        areaKey: [[tierColor, 'Tier 1B boundaries'], [absent, 'Temporary exemptions only']],
      },
      {title: 'Temporary exemptions without Tier 1B',
        description: 'These municipalities have temporary exemptions but no Tier 1B area in their region’s selected map stage. The saved maps do not establish why.',
        stats: [{select: hasTier, label: 'Has Tier 1B', color: good},
          {select: lostTier, label: 'Temporary exemptions only', color: bad},
          {select: p => !p.has_likely_eligible && !hasTier(p), label: 'Neither', color: absent}],
        areaKey: [[tierColor, 'Tier 1B boundaries'], [bad, 'Temporary exemptions only']],
      },
    ];
    // A phase changes only its selected features. Reverse playback traverses
    // these same phases and gaps in reverse, including partially played phases.
    const phase = (kind, select, style) => item => item.kind === kind && select(item.props)
      ? (typeof style === 'function' ? style(item.props) : style) : {};
    const groups = [
      [ // Boundaries → designated areas
        phase('area', () => true, {color: good, fillColor: good, opacity: 1, fillOpacity: 0.75}),
        phase('town', p => p.has_designated_area, {fillColor: gain, fillOpacity: 0.6}),
        phase('town', p => !p.has_designated_area, {fillColor: bad, fillOpacity: 0.6}),
      ],
      [ // Designated areas → likely exemption eligibility
        item => ({...phase('area', () => true, {color: good, fillColor: good})(item),
          ...phase('town', p => p.has_designated_area, {fillColor: good})(item),
          ...phase('town', p => !p.has_designated_area, {fillColor: absent})(item)}),
        phase('area', p => p.likely_eligible !== true, p => ({color: areaColor(p.likely_eligible), fillColor: areaColor(p.likely_eligible)})),
        phase('town', p => p.has_designated_area && !p.has_likely_eligible, {fillColor: bad}),
      ],
      [ // Likely exemptions → Tier 1B stage comparison
        item => ({...phase('town', p => !p.has_likely_eligible, {fillColor: absent})(item),
          ...phase('area', () => true, p => remainingExempt(p)
            ? {color: absent, fillColor: absent} : {opacity: 0, fillOpacity: 0})(item),
          ...phase('tier', () => true, {opacity: 0.9, fillOpacity: 0.6})(item)}),
        phase('town', gainedTier, {fillColor: gain}),
      ],
      [ // Cool down gains, then show temporary exemptions without Tier 1B.
        phase('town', gainedTier, {fillColor: good}),
        item => ({...phase('town', lostTier, {fillColor: bad})(item),
          ...phase('area', remainingExempt, {color: bad, fillColor: bad})(item)}),
      ],
    ];
    return {steps, groups, overlays: ['area', 'tier']};
  },
});
