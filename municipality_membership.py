"""Approved local derivation of interim-area municipality membership.

Source labels and geometry are never rewritten. See MUNICIPALITY_MEMBERSHIP.md.
"""

MEMBERSHIP_VERSION = 1
ALIASES = {
    'algiers': ('Guilford',),
    'enosburg': ('Enosburgh',),
    'essex town': ('Essex',),
    'ferrisburg': ('Ferrisburgh',),
    'greensborro': ('Greensboro',),
    'jericho\\underhill': ('Jericho', 'Underhill'),
    'middletown': ('Middletown Springs',),
    'n hero': ('North Hero',),
    's shaftsbury': ('Shaftsbury',),
    'st. albans city': ('Saint Albans City',),
    'st. albans town': ('Saint Albans Town',),
    'st. johnsbury': ('Saint Johnsbury',),
    'tyson': ('Plymouth',),
    'village of manchester': ('Manchester',),
    'west brattleboro': ('Brattleboro',),
}
RUTLAND_FEATURES = frozenset(f'95d37a2dfaaeb934:{oid}' for oid in (21, 22, 23))


def normalize(value):
    return ' '.join((value or '').split()).casefold()


def derive_memberships(areas, towns):
    """Return one relationship per source area and official municipality GEOID.

    Missing labels, targets, ambiguous boundaries, or unreviewed Rutland records
    fail explicitly. Geometry is not consulted, even when it is missing.
    """
    by_name, geoids = {}, set()
    for town in towns:
        key, geoid = normalize(town['municipality']), town['geoid']
        if not key or not geoid or key in by_name or geoid in geoids:
            raise ValueError(f'Ambiguous/missing municipality name or GEOID: {town}')
        by_name[key] = town
        geoids.add(geoid)
    result, seen = [], set()
    for area in areas:
        fid, key = area['feature_id'], normalize(area['municipality'])
        if fid in seen:
            raise ValueError(f'Duplicate source area: {fid}')
        seen.add(fid)
        if key == 'rutland':
            if fid not in RUTLAND_FEATURES or area['category'] != 'town_growth_development':
                raise ValueError(f'Review municipality membership for {fid}: Rutland')
            targets, method = ('Rutland City',), 'approved_feature_override'
        elif key in ALIASES:
            targets, method = ALIASES[key], 'approved_alias'
        elif key in by_name:
            targets, method = (by_name[key]['municipality'],), 'normalized_exact'
        else:
            raise ValueError(f'Review municipality membership for {fid}: {area["municipality"]!r}')
        for target in targets:
            town = by_name.get(normalize(target))
            if town is None:
                raise ValueError(f'Missing approved municipality target {target} for {fid}')
            result.append({'feature_id': fid, 'source_municipality': area['municipality'],
                           'municipality': town['municipality'], 'municipality_geoid': town['geoid'],
                           'method': method})
    return result
