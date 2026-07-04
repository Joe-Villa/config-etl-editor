"""Hardcoded paths and schema constants for collect_origin_data."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PACKAGE_ROOT / "data"
SRC_DIR = PACKAGE_ROOT / "src"

# state_regions 资源列（原 data/地区信息/resource.json）
RESOURCE_COLUMNS: list[str] = [
    "building_logging_camp",
    "building_fishing_wharf",
    "building_iron_mine",
    "building_coal_mine",
    "building_lead_mine",
    "building_sulfur_mine",
    "building_whaling_station",
    "building_gold_mine",
    "building_oil_rig",
    "building_rubber_plantation",
    "building_gold_field",
]

REL_STATE_REGIONS = "map_data/state_regions"
REL_POPS = "common/history/pops"
REL_DIPLOMACY = "common/history/diplomacy"
REL_POWER_BLOCS = "common/history/power_blocs"
REL_STATES = "common/history/states"
REL_BUILDINGS = "common/history/buildings"
REL_COUNTRIES = "common/history/countries"
REL_COUNTRY_DEFINITIONS = "common/country_definitions"
REL_NAMED_COLORS = "common/named_colors"

TABLE_DIR = PACKAGE_ROOT / "table"

METADATA_JSON = "metadata.json"
ORIGIN_DB = "origin.sqlite"
