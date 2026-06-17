from pathlib import Path
from pyproj import Geod

ROOT = Path(__file__).resolve().parent
IN_DIR = ROOT / "in"
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"
DB_PATH = DATA_DIR / "act181.duckdb"

SQ_M_PER_SQ_MI = 2589988.110336
GEOD = Geod(ellps="WGS84")

RPC_CODES = {
    "AC": "Addison County Regional Planning Commission",
    "BC": "Bennington County Regional Planning Commission",
    "CV": "Central Vermont Regional Planning Commission",
    "CC": "Chittenden County Regional Planning Commission",
    "LC": "Lamoille County Planning Commission",
    "NV": "Northeastern Vermont Development Association",
    "NW": "Northwest Regional Planning Commission",
    "RR": "Rutland Regional Planning Commission",
    "MA": "Mount Ascutney Regional Commission",
    "TR": "Two Rivers-Ottauquechee Regional Commission",
    "WR": "Windham Regional Commission",
}

GROWTH_CODES = {
    "DC": "Downtown Center",
    "VC": "Village Center",
    "VA": "Village Area",
    "PGA": "Planned Growth Area",
}

SOURCES = {
    "flu_consolidated": {
        "url": "https://services1.arcgis.com/rnCtPMpypTkqwvYT/arcgis/rest/services/VT_FLUMAP_poly_SP_Public/FeatureServer/1",
        "domain": "flu",
    },
    "tier_consolidated": {
        "url": "https://services1.arcgis.com/rnCtPMpypTkqwvYT/arcgis/rest/services/VT_TIERMAP_poly_SP_Public/FeatureServer/0",
        "domain": "tier",
    },
    "flu_nw_pre": {
        "url": "https://services7.arcgis.com/CIdxNzJmLZGoegAM/arcgis/rest/services/NW_FLUMAP_PRE_poly_2025/FeatureServer/0",
        "domain": "flu",
    },
    "flu_rr_pre": {
        "url": "https://services1.arcgis.com/rnCtPMpypTkqwvYT/arcgis/rest/services/vtFutureLandUse_RRPC_poly_20250902/FeatureServer/1",
        "domain": "flu",
    },
    "tier_ma_pre": {
        "url": "https://services5.arcgis.com/tbnCzQ0iyXeEj5i5/arcgis/rest/services/MA_TIER1B_PRE_poly_sp_2026/FeatureServer/0",
        "domain": "tier",
    },
    "tier_lc_pre": {
        "url": "https://services2.arcgis.com/aYpp0a2OASkHuYP7/arcgis/rest/services/LC_TIER1B_PRE_poly_2025/FeatureServer/0",
        "domain": "tier",
    },
    "tier_nw_pre": {
        "url": "https://services7.arcgis.com/CIdxNzJmLZGoegAM/arcgis/rest/services/NW_TIER1B_PRE_poly_2025/FeatureServer/0",
        "domain": "tier",
    },
    "tier_rr_pre": {
        "url": "https://services1.arcgis.com/rnCtPMpypTkqwvYT/arcgis/rest/services/Proposed_Tier_1B_Areas/FeatureServer/2",
        "domain": "tier",
    },
    "tier_cc_pre": {
        "url": "https://services1.arcgis.com/KVHZNprt62ZdIujN/arcgis/rest/services/CC_TIER1B_PREAPPLICATION_poly_SP_2025/FeatureServer/1",
        "domain": "tier",
    },
    "tier_ac_pre": {
        "url": "https://services8.arcgis.com/Gf7J70KyUdpb0dNE/arcgis/rest/services/AC_TIER1B_PRE_poly_2026/FeatureServer/1",
        "domain": "tier",
    },
    "boundary_towns": {
        "url": "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/FS_VCGI_OPENDATA_Boundary_BNDHASH_poly_towns_SP_v1/FeatureServer/0",
        "domain": "boundary",
    },
    "boundary_counties": {
        "url": "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/FS_VCGI_OPENDATA_Boundary_BNDHASH_poly_counties_SP_v1/FeatureServer/0",
        "domain": "boundary",
    },
    "boundary_rpcs": {
        "url": "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services/FS_VCGI_OPENDATA_Boundary_BNDHASH_poly_rpcs_SP_v1/FeatureServer/0",
        "domain": "boundary",
    },
}

TIER1B_SOURCES = {
    "tier_nw_pre", "tier_rr_pre", "tier_cc_pre", "tier_ac_pre",
    "tier_ma_pre", "tier_lc_pre",
}

FIELD_MAPS = {
    "flu_consolidated": {
        "OBJECTID": "source_oid",
        "FLU_AREA": "flu_code",
        "NAME": "name",
        "RPC": "rpc",
        "NOTES": "notes",
        "VERS_RPC": "version",
        "DATE_RPC": "date_rpc",
        "DESIG_CS": "desig_center_step",
        "DESIG_TYP": "desig_type",
        "DATE_LURB": "date_lurb",
        "GEOID": "geoid",
        "LURBSTATUS": "lurb_status",
        "DATE_AGG": "date_agg",
        "LU_AUTH": "lu_auth",
    },
    "tier_consolidated": {
        "OBJECTID": "source_oid",
        "TIER_AREA": "tier_code",
        "SUBMITTER": "submitter",
        "RPC": "rpc",
        "NOTES": "notes",
        "TIER_VERS": "version",
        "DATE_SUBM": "date_subm",
        "LURBSTATUS": "lurb_status",
        "DATE_LURB": "date_lurb",
        "GEOID": "geoid",
        "DATE_AGG": "date_agg",
    },
    "flu_nw_pre": {
        "OBJECTID": "source_oid",
        "FLU_AREA": "flu_code",
        "NAME": "name",
        "RPC": "rpc",
        "NOTES": "notes",
        "VERS_RPC": "version",
        "DATE_RPC": "date_rpc",
    },
    "flu_rr_pre": {
        "FID": "source_oid",
        "FLU_AREA": "flu_code",
        "NAME": "name",
        "RPC": None,
        "RPC_CODE": "rpc",
        "MUNI": None,
        "GEOID": "geoid",
        "NOTES": "notes",
        "DATE": "date_rpc",
        "DESIG_CS": "desig_center_step",
        "DESIG_TYP": "desig_type",
        "VERSION": "version",
    },
    "tier_ma_pre": {
        "OBJECTID": "source_oid",
        "NAME": "name",
        "RPC": "rpc",
        "NOTES": "notes",
        "DATE_RPC": "date_subm",
        "TIER_AREA": "tier_code",
        "SUBMITTER": "submitter",
        "TIER_VERS": "version",
    },
    "tier_lc_pre": {
        "FID": "source_oid",
        "RPC": "rpc",
        "NOTES": "notes",
        "TIER_AREA": "tier_code",
        "Submitter": "submitter",
        "TIER_VERS": "version",
        "DATE_SUBM": "date_subm",
    },
    "tier_nw_pre": {
        "OBJECTID": "source_oid",
        "FLU_AREA": None,
        "NAME": "name",
        "RPC": "rpc",
        "NOTES": "notes",
        "VERS_RPC": "version",
        "DATE_RPC": "date_subm",
    },
    "tier_rr_pre": {
        "FID": "source_oid",
        "FLU_AREA": None,
        "NAME": "name",
        "RPC": None,
        "RPC_CODE": "rpc",
        "MUNI": None,
        "GEOID": "geoid",
        "NOTES": "notes",
        "DATE": "date_subm",
        "DESIG_CS": None,
        "DESIG_TYP": None,
        "VERSION": "version",
    },
    "tier_cc_pre": {
        "OBJECTID": "source_oid",
        "FLU_Area": None,
        "TOWNGEOID": None,
        "NAME": "name",
        "RPC": "rpc",
        "DATE_RPC": "date_subm",
        "VERS_RPC": "version",
        "DESIG_CS": None,
        "DESIG_TYP": None,
        "LURBSTATUS": "lurb_status",
        "DATE_AGG": "date_agg",
        "GEOID": None,
        "NOTES": "notes",
    },
    "tier_ac_pre": {
        "OBJECTID": "source_oid",
        "FLU_AREA": None,
        "NAME": "name",
        "RPC": "rpc",
        "NOTES": "notes",
        "VERS_RPC": "version",
        "DATE_RPC": "date_subm",
    },
    "boundary_towns": {
        "OBJECTID": "source_oid",
        "TOWNNAME": "name",
        "TOWNGEOID": "geoid",
    },
    "boundary_counties": {
        "OBJECTID": "source_oid",
        "CNTYNAME": "name",
        "CNTYGEOID": "geoid",
    },
    "boundary_rpcs": {
        "OBJECTID": "source_oid",
        "RPC": "rpc_code",
        "SHORTNAME": "name",
    },
}

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

BOUNDARY_TYPE_MAP = {
    "_towns": "town",
    "_counties": "county",
    "_rpcs": "rpc",
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

WINDHAM_TOWNS = {
    "Putney", "Bellows Falls", "Brattleboro", "Saxtons River",
    "Weston", "Newfane", "South Newfane", "North Westminster",
    "West Brattleboro", "Williamsville", "Westminster",
    "Bondville", "Marlboro", "Westminster Station",
    "Westminster West", "Cambridgeport", "Dummerston",
    "Guilford", "Halifax", "Jamaica", "Londonderry",
    "Marlboro", "Rockingham", "Stratton", "Townshend",
    "Vernon", "Wardsboro", "Westminster", "Whitingham",
    "Wilmington", "Windham", "Winhall",
}

FLU_COLUMNS = [
    "id", "geom", "flu_code", "name", "rpc", "version",
    "submitter", "geoid", "desig_center_step", "desig_type",
    "lurb_status", "date_rpc", "date_lurb", "date_agg", "notes",
    "lu_auth", "source_layer", "source_oid",
]

TIER_COLUMNS = [
    "id", "geom", "tier_code", "rpc", "version",
    "submitter", "geoid", "lurb_status", "date_subm",
    "date_lurb", "date_agg", "notes", "source_layer", "source_oid",
]

BOUNDARY_COLUMNS = [
    "id", "geom", "boundary_type", "name", "geoid",
    "rpc_code", "source_layer", "source_oid",
]
