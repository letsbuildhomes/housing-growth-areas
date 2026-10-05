"""Shared paths for the current research pipeline."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IN_DIR = ROOT / 'in'
DATA_DIR = ROOT / 'data'
OUT_DIR = ROOT / 'out'
SNAPSHOT_ROOT = IN_DIR / 'snapshots'
DB_PATH = DATA_DIR / 'act181_ingest.duckdb'
DASHBOARD_DIR = OUT_DIR / 'dashboard'
EXPORT_DIR = DASHBOARD_DIR / 'data'
MEMBERSHIP_PATH = DATA_DIR / 'municipality-memberships.json'
TIER_RULES = {'version': 2, 'crs': 'EPSG:32145', 'boundary_band_m': 75,
              'closing_radius_m': 1.5, 'minimum_part_m2': 1}
HOUSING_PATH = DATA_DIR / 'housing-growth.json'
HOUSING_RULES = {'version': 5, **{k: v for k, v in TIER_RULES.items() if k != 'version'},
                 'categories': ['VA', 'VC', 'PGA', 'DC'],
                 'grouping_gap_m': 100,
                 'missing_flu_policy': 'unknown code or missing housing geometry',
                 'coverage_sliver_m': 2,
                 'coverage_near_complete_fraction': 0.01,
                 'coverage_tolerance_fraction': 0.05,
                 'coverage_tolerance_m2': 1000,
                 'reverse_near_complete_fraction': 0.01,
                 'reverse_tolerance_fraction': 0.05,
                 'reverse_tolerance_m2': 1000}


# Publisher value mappings

VERSION_NORMALIZE = {
    "PRE": "PRE",
    "APP": "APP",
    "AMD": "AMD",
    "Pre-Application": "PRE",
    "Pre-Application Determination of Compliance": "PRE",
    "Application": "APP",
}

RPC_NAME_TO_CODE = {
    "Addison County Regional Planning Commission": "AC",
    "Bennington County Regional Planning Commission": "BC",
    "Central Vermont Regional Planning Commission": "CV",
    "Chittenden County Regional Planning Commission": "CC",
    "Lamoille County Planning Commission": "LC",
    "Northeastern Vermont Development Association": "NV",
    "Northwest Regional Planning Commission": "NW",
    "Rutland Regional Planning Commission": "RR",
    "Mount Ascutney Regional Commission": "MA",
    "Two Rivers-Ottauquechee Regional Commission": "TR",
    "Windham Regional Commission": "WR",
}

FLU_NAME_TO_CODE = {
    "Downtown Center": "DC",
    "Village Center": "VC",
    "Planned Growth Area": "PGA",
    "Village Area": "VA",
    "Special Use": "SU",
    "Transition or Infill": "TI",
    "Enterprise": "ENT",
    "Resource Based Recreation": "RBR",
    "Hamlet": "HAM",
    "Rural General": "RG",
    "Rural Ag or Forestry": "RAF",
    "Rural Ag/Forestry": "RAF",
    "Rural Conservation": "RC",
    "Surface Water": "SW",
}



# Approved municipality exceptions (reviewed September 12, 2026)

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
