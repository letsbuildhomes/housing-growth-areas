# Approved municipality membership

Status: **approved and implemented** in `municipality_membership.py`, including Rutland City and Plymouth for Tyson. Reviewed September 12, 2026 against the saved snapshot. No source records or geometries have been modified. The tables below preserve the approved decisions and their dated impact. Current feature IDs and membership GEOIDs are exported in `map.json`.

## Recommendation

Add a derived membership step to the current export pipeline, separate from legacy `transform.py`. Keep the research database read-only. Match labels using whitespace/case normalization, then apply the explicit exceptions below. Resolve official municipality GEOIDs from the saved boundary dataset. Unrecognized or ambiguous future labels must produce an actionable error/review list rather than silently fall back to geometry.

Keep the existing source-label table grouping and all 319 source features. Use a distinct `(feature_id, municipality_geoid)` relationship for map town summaries. Source-area counts use distinct feature IDs; municipality counts use distinct GEOIDs. Eligibility remains the publisher’s true/false/null status. Future transit layers can have a separate documented spatial-membership method.

## Exceptions for approval

| Source label (case-insensitive) | Proposed municipality membership | Records | Basis / scope |
|---|---|---:|---|
| ALGIERS | Guilford | 1 | Locality; saved polygon lies in Guilford. |
| ENOSBURG | Enosburgh | 1 | Spelling; Enosburg Falls polygon lies in Enosburgh. |
| ESSEX TOWN | Essex | 1 | Town suffix; do not merge Essex Junction. |
| FERRISBURG | Ferrisburgh | 1 | Spelling variant. |
| GREENSBORRO | Greensboro | 2 | Misspelling; both named Greensboro centers. Greensboro Bend also extends into three neighbors; those intersections do not create membership. |
| JERICHO\UNDERHILL | Jericho + Underhill | 1 | Explicit shared label and user confirmation: one area, two memberships. |
| MIDDLETOWN | Middletown Springs | 1 | Full town name; area name is Middletown Springs Village Center. |
| N HERO | North Hero | 1 | Abbreviation. |
| Rutland | Rutland City | 3 | Feature-specific rule for the three current NDA records (IDs 21, 22, 23), all wholly within Rutland City. Do not assume every future “Rutland” label means the city. |
| S SHAFTSBURY | Shaftsbury | 1 | South Shaftsbury locality. |
| ST. ALBANS CITY / St. Albans City | Saint Albans City | 2 | Saint expansion; preserve city/town distinction. |
| ST. ALBANS TOWN | Saint Albans Town | 1 | Saint expansion; preserve city/town distinction. |
| ST. JOHNSBURY / St. Johnsbury | Saint Johnsbury | 2 | Saint expansion. |
| TYSON | Plymouth | 1 | Propose Plymouth as designation owner; see the special review below. |
| VILLAGE OF MANCHESTER | Manchester | 1 | Village is represented within Manchester by this municipal-boundary dataset. |
| West Brattleboro | Brattleboro | 1 | Locality; current NDA is wholly in Brattleboro. |

## Shared areas and clipping

Riverside/Underhill Flats (`a8a69a8957ab82c6:50`) receives two membership rows, Jericho and Underhill, pointing to the same original feature. This yields 320 membership relationships for 319 areas. Both municipalities already have other likely eligible areas in this snapshot.

Do not duplicate the source area or split it in storage. Optional derived map fragments can later use `ST_Intersection(area.geom, member_town.geom)` and retain `parent_feature_id`, target GEOID, and a fragment ID. Count the parent, not the fragments. Clipping would follow the actual boundary, not split the area in half. It requires checking validity, polygon-only output, non-empty parts, and residual/overlap geometry; source geometries remain untouched. Membership-only is simpler and sufficient for the current problem.

## Tyson: explicit review point

The current source label is TYSON rather than a municipality. The saved buffered polygon crosses Plymouth and Ludlow. Plymouth’s official site says it received village-center designation for Tyson and Plymouth Union; its zoning ordinance identifies both as Plymouth centers. Ludlow’s plan describes the hamlet as straddling the town line. I therefore propose Plymouth-only **designation membership**, not an assertion that the entire hamlet or buffer lies in Plymouth. Approve this explicitly, or request shared membership after checking the original designation map. Adding Ludlow would not change statewide town totals in this snapshot because Ludlow already has its own likely eligible area.

Sources: [Plymouth official site](https://plymouthvt.org/wordpress/), [Plymouth zoning ordinance](https://plymouthvt.org/wordpress/wp-content/uploads/2023/03/PLYMOUTH-ZONING-ORDINANCE-ADOPTED-5-21-2024.pdf), [Ludlow plan](https://www.ludlow.vt.us/vertical/sites/%7B78E8DA21-0D46-4486-AF59-9D2B5A1048F3%7D/uploads/Planning_Commission_March_Agenda__Supporting_Documents1.pdf). The source references `VDtyson.pdf`; that original designation map was not retrieved during this review.

## Expected impact (proposal simulation only)

All 319 records have labels. 298 records match after case/whitespace normalization; 21 records need the 16 exception rules. All exact-label records intersect their named municipality; intersection was used only as an audit diagnostic, not as the proposed assignment rule.

| Municipality summary | Current intersections | Proposed membership |
|---|---:|---:|
| With designated areas | 195 | 187 |
| With a likely eligible area | 126 | 118 |
| With areas, none likely eligible | 69 | 69 |
| No designated areas | 61 | 69 |

| Municipality | Current | Proposed |
|---|---|---|
| Dummerston | Likely eligible area | No designated areas |
| Fayston | Likely eligible area | No designated areas |
| Jamaica | Likely eligible area | Areas, none likely eligible |
| Johnson | Likely eligible area | Areas, none likely eligible |
| Leicester | Likely eligible area | No designated areas |
| Mount Holly | Likely eligible area | Areas, none likely eligible |
| Mount Tabor | Areas, none likely eligible | No designated areas |
| Ryegate | Likely eligible area | Areas, none likely eligible |
| Sheffield | Areas, none likely eligible | No designated areas |
| Stannard | Areas, none likely eligible | No designated areas |
| Sutton | Likely eligible area | No designated areas |
| Walden | Areas, none likely eligible | No designated areas |

## Complete label mapping

The following includes every normalized source-label group, including unchanged names. The current map export contains every feature ID and membership GEOID.

| Source labels | Official municipality membership | Records | Rule |
|---|---|---:|---|
| ADDISON | Addison | 1 | normalized_exact |
| ALBANY | Albany | 1 | normalized_exact |
| ALBURGH | Alburgh | 1 | normalized_exact |
| ALGIERS | Guilford | 1 | exception |
| ARLINGTON | Arlington | 2 | normalized_exact |
| BAKERSFIELD | Bakersfield | 1 | normalized_exact |
| BARNARD | Barnard | 1 | normalized_exact |
| BARNET | Barnet | 4 | normalized_exact |
| BARRE CITY | Barre City | 1 | normalized_exact |
| BARRE TOWN | Barre Town | 4 | normalized_exact |
| BARTON / Barton | Barton | 2 | normalized_exact |
| BENNINGTON / Bennington | Bennington | 3 | normalized_exact |
| BENSON | Benson | 1 | normalized_exact |
| BERKSHIRE | Berkshire | 2 | normalized_exact |
| BERLIN / Berlin | Berlin | 5 | normalized_exact |
| BETHEL | Bethel | 1 | normalized_exact |
| BRADFORD | Bradford | 1 | normalized_exact |
| BRAINTREE | Braintree | 1 | normalized_exact |
| BRANDON | Brandon | 1 | normalized_exact |
| BRATTLEBORO / Brattleboro | Brattleboro | 3 | normalized_exact |
| BRIDGEWATER | Bridgewater | 2 | normalized_exact |
| BRIGHTON | Brighton | 1 | normalized_exact |
| BRISTOL | Bristol | 1 | normalized_exact |
| BROOKFIELD | Brookfield | 1 | normalized_exact |
| BROWNINGTON | Brownington | 1 | normalized_exact |
| BURKE | Burke | 2 | normalized_exact |
| BURLINGTON / Burlington | Burlington | 2 | normalized_exact |
| CABOT | Cabot | 1 | normalized_exact |
| CALAIS | Calais | 4 | normalized_exact |
| CAMBRIDGE | Cambridge | 2 | normalized_exact |
| CANAAN | Canaan | 2 | normalized_exact |
| CASTLETON | Castleton | 3 | normalized_exact |
| CAVENDISH | Cavendish | 2 | normalized_exact |
| CHARLOTTE | Charlotte | 2 | normalized_exact |
| CHELSEA | Chelsea | 1 | normalized_exact |
| CHESTER / Chester | Chester | 2 | normalized_exact |
| CHITTENDEN | Chittenden | 2 | normalized_exact |
| CLARENDON | Clarendon | 1 | normalized_exact |
| COLCHESTER / Colchester | Colchester | 2 | normalized_exact |
| CONCORD | Concord | 1 | normalized_exact |
| CORINTH | Corinth | 2 | normalized_exact |
| CORNWALL | Cornwall | 1 | normalized_exact |
| COVENTRY | Coventry | 1 | normalized_exact |
| CRAFTSBURY | Craftsbury | 3 | normalized_exact |
| DANBY | Danby | 1 | normalized_exact |
| DANVILLE | Danville | 3 | normalized_exact |
| DERBY | Derby | 1 | normalized_exact |
| DORSET | Dorset | 2 | normalized_exact |
| DOVER | Dover | 2 | normalized_exact |
| EAST MONTPELIER | East Montpelier | 2 | normalized_exact |
| ELMORE | Elmore | 1 | normalized_exact |
| ENOSBURG | Enosburgh | 1 | exception |
| ESSEX JUNCTION / Essex Junction | Essex Junction | 2 | normalized_exact |
| ESSEX TOWN | Essex | 1 | exception |
| FAIR HAVEN | Fair Haven | 1 | normalized_exact |
| FAIRFAX | Fairfax | 1 | normalized_exact |
| FAIRFIELD | Fairfield | 2 | normalized_exact |
| FAIRLEE | Fairlee | 1 | normalized_exact |
| FERRISBURG | Ferrisburgh | 1 | exception |
| FRANKLIN | Franklin | 1 | normalized_exact |
| GLOVER | Glover | 2 | normalized_exact |
| GRAFTON | Grafton | 1 | normalized_exact |
| GRAND ISLE | Grand Isle | 1 | normalized_exact |
| GRANVILLE | Granville | 2 | normalized_exact |
| GREENSBORRO | Greensboro | 2 | exception |
| GROTON | Groton | 1 | normalized_exact |
| GUILFORD | Guilford | 1 | normalized_exact |
| HANCOCK | Hancock | 1 | normalized_exact |
| HARDWICK | Hardwick | 2 | normalized_exact |
| HARTFORD / Hartford | Hartford | 4 | normalized_exact |
| HARTLAND | Hartland | 3 | normalized_exact |
| HIGHGATE / Highgate | Highgate | 4 | normalized_exact |
| HINESBURG / Hinesburg | Hinesburg | 3 | normalized_exact |
| HOLLAND | Holland | 1 | normalized_exact |
| HUNTINGTON | Huntington | 2 | normalized_exact |
| HYDE PARK | Hyde Park | 2 | normalized_exact |
| IRA | Ira | 1 | normalized_exact |
| IRASBURG | Irasburg | 1 | normalized_exact |
| JAMAICA | Jamaica | 1 | normalized_exact |
| JERICHO | Jericho | 2 | normalized_exact |
| JERICHO\UNDERHILL | Jericho + Underhill | 1 | exception |
| JOHNSON | Johnson | 1 | normalized_exact |
| LONDONDERRY | Londonderry | 2 | normalized_exact |
| LUDLOW | Ludlow | 1 | normalized_exact |
| LUNENBURG | Lunenburg | 2 | normalized_exact |
| LYNDON | Lyndon | 1 | normalized_exact |
| MANCHESTER / Manchester | Manchester | 2 | normalized_exact |
| MARLBORO | Marlboro | 1 | normalized_exact |
| MARSHFIELD | Marshfield | 1 | normalized_exact |
| MENDON | Mendon | 1 | normalized_exact |
| MIDDLEBURY / Middlebury | Middlebury | 3 | normalized_exact |
| MIDDLESEX | Middlesex | 1 | normalized_exact |
| MIDDLETOWN | Middletown Springs | 1 | exception |
| MILTON | Milton | 1 | normalized_exact |
| MONKTON | Monkton | 1 | normalized_exact |
| MONTGOMERY | Montgomery | 2 | normalized_exact |
| MONTPELIER / Montpelier | Montpelier | 2 | normalized_exact |
| MORETOWN | Moretown | 1 | normalized_exact |
| MORRISTOWN | Morristown | 1 | normalized_exact |
| MOUNT HOLLY | Mount Holly | 1 | normalized_exact |
| N HERO | North Hero | 1 | exception |
| NEW HAVEN | New Haven | 1 | normalized_exact |
| NEWBURY | Newbury | 2 | normalized_exact |
| NEWFANE | Newfane | 3 | normalized_exact |
| NEWPORT CITY | Newport City | 1 | normalized_exact |
| NORTHFIELD | Northfield | 2 | normalized_exact |
| NORWICH | Norwich | 1 | normalized_exact |
| ORANGE | Orange | 1 | normalized_exact |
| ORWELL | Orwell | 1 | normalized_exact |
| PAWLET | Pawlet | 2 | normalized_exact |
| PEACHAM | Peacham | 1 | normalized_exact |
| PERU | Peru | 1 | normalized_exact |
| PITTSFIELD | Pittsfield | 1 | normalized_exact |
| PITTSFORD | Pittsford | 1 | normalized_exact |
| PLAINFIELD / Plainfield | Plainfield | 2 | normalized_exact |
| PLYMOUTH | Plymouth | 1 | normalized_exact |
| POULTNEY | Poultney | 2 | normalized_exact |
| POWNAL | Pownal | 3 | normalized_exact |
| PROCTOR | Proctor | 1 | normalized_exact |
| PUTNEY / Putney | Putney | 3 | normalized_exact |
| RANDOLPH / Randolph | Randolph | 4 | normalized_exact |
| READING | Reading | 1 | normalized_exact |
| READSBORO | Readsboro | 1 | normalized_exact |
| RICHFORD | Richford | 1 | normalized_exact |
| RICHMOND | Richmond | 1 | normalized_exact |
| ROCHESTER | Rochester | 1 | normalized_exact |
| ROCKINGHAM | Rockingham | 2 | normalized_exact |
| ROXBURY | Roxbury | 1 | normalized_exact |
| ROYALTON | Royalton | 2 | normalized_exact |
| RUPERT | Rupert | 2 | normalized_exact |
| Rutland | Rutland City | 3 | exception |
| RUTLAND CITY | Rutland City | 1 | normalized_exact |
| RYEGATE | Ryegate | 3 | normalized_exact |
| S SHAFTSBURY | Shaftsbury | 1 | exception |
| SALISBURY | Salisbury | 1 | normalized_exact |
| SHAFTSBURY | Shaftsbury | 1 | normalized_exact |
| SHARON | Sharon | 1 | normalized_exact |
| SHELBURNE | Shelburne | 1 | normalized_exact |
| SHELDON | Sheldon | 2 | normalized_exact |
| Shoreham | Shoreham | 1 | normalized_exact |
| SOUTH BURLINGTON / South Burlington | South Burlington | 2 | normalized_exact |
| SOUTH HERO | South Hero | 2 | normalized_exact |
| SPRINGFIELD | Springfield | 1 | normalized_exact |
| ST. ALBANS CITY / St. Albans City | Saint Albans City | 2 | exception |
| ST. ALBANS TOWN | Saint Albans Town | 1 | exception |
| ST. JOHNSBURY / St. Johnsbury | Saint Johnsbury | 2 | exception |
| STAMFORD | Stamford | 1 | normalized_exact |
| STARKSBORO | Starksboro | 2 | normalized_exact |
| STOWE | Stowe | 2 | normalized_exact |
| STRAFFORD | Strafford | 2 | normalized_exact |
| SUDBURY | Sudbury | 1 | normalized_exact |
| SUNDERLAND | Sunderland | 1 | normalized_exact |
| SWANTON | Swanton | 1 | normalized_exact |
| THETFORD | Thetford | 5 | normalized_exact |
| TINMOUTH | Tinmouth | 1 | normalized_exact |
| TOPSHAM | Topsham | 3 | normalized_exact |
| TOWNSHEND | Townshend | 2 | normalized_exact |
| TROY | Troy | 2 | normalized_exact |
| TUNBRIDGE | Tunbridge | 2 | normalized_exact |
| TYSON | Plymouth | 1 | exception |
| UNDERHILL | Underhill | 1 | normalized_exact |
| VERGENNES / Vergennes | Vergennes | 5 | normalized_exact |
| VERNON | Vernon | 1 | normalized_exact |
| VERSHIRE | Vershire | 1 | normalized_exact |
| VILLAGE OF MANCHESTER | Manchester | 1 | exception |
| WAITSFIELD / Waitsfield | Waitsfield | 3 | normalized_exact |
| WALLINGFORD | Wallingford | 3 | normalized_exact |
| WARDSBORO | Wardsboro | 1 | normalized_exact |
| WARREN | Warren | 1 | normalized_exact |
| WATERBURY | Waterbury | 2 | normalized_exact |
| WATERFORD | Waterford | 1 | normalized_exact |
| WATERVILLE | Waterville | 1 | normalized_exact |
| WEATHERSFIELD / Weathersfield | Weathersfield | 2 | normalized_exact |
| WELLS | Wells | 1 | normalized_exact |
| West Brattleboro | Brattleboro | 1 | exception |
| WEST FAIRLEE | West Fairlee | 1 | normalized_exact |
| WEST RUTLAND | West Rutland | 1 | normalized_exact |
| WEST WINDSOR | West Windsor | 1 | normalized_exact |
| WESTFIELD | Westfield | 1 | normalized_exact |
| WESTFORD / Westford | Westford | 3 | normalized_exact |
| WESTMINSTER | Westminster | 4 | normalized_exact |
| WESTON | Weston | 1 | normalized_exact |
| WHEELOCK | Wheelock | 1 | normalized_exact |
| WHITING | Whiting | 1 | normalized_exact |
| WHITINGHAM | Whitingham | 2 | normalized_exact |
| WILLIAMSTOWN | Williamstown | 1 | normalized_exact |
| WILLISTON / Williston | Williston | 2 | normalized_exact |
| WILMINGTON | Wilmington | 2 | normalized_exact |
| WINDSOR | Windsor | 1 | normalized_exact |
| WINHALL | Winhall | 1 | normalized_exact |
| WINOOSKI / Winooski | Winooski | 2 | normalized_exact |
| WOLCOTT | Wolcott | 2 | normalized_exact |
| WOODSTOCK | Woodstock | 2 | normalized_exact |
| WORCESTER | Worcester | 1 | normalized_exact |
