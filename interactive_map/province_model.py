"""Province semantic labels: static geographic base + editable scenario overlay."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import sqlite3
from interactive_map.db_reader import (
    load_hub_provinces,
    load_impassable_keys,
    load_land_province_keys,
    load_prime_land_keys,
    load_province_geographic_state,
    load_province_tag_state,
    load_sea_province_keys,
    load_tag_country_types,
    load_tag_state_types,
)
from interactive_map.png_util import province_rgb_keys_from_bytes


@dataclass
class StaticMapBase:
    """Geographic labels from ref_* + map_png only; immutable after database build."""

    terrain: dict[int, str] = field(default_factory=dict)
    hub: dict[int, str] = field(default_factory=dict)
    hub_info: dict[int, dict[str, str]] = field(default_factory=dict)
    province_geographic_state: dict[int, str] = field(default_factory=dict)


@dataclass
class ScenarioOverlay:
    """Editable scenario data from geo_* / st_* tables."""

    ownership_tag: dict[int, str] = field(default_factory=dict)
    incorporation: dict[int, str] = field(default_factory=dict)
    country_type: dict[int, str] = field(default_factory=dict)
    province_tag_state: dict[int, tuple[str, str]] = field(default_factory=dict)


@dataclass
class ProvinceModel:
    """Merged view for rendering and tooltips."""

    rgb_keys: np.ndarray
    terrain: dict[int, str] = field(default_factory=dict)
    hub: dict[int, str] = field(default_factory=dict)
    incorporation: dict[int, str] = field(default_factory=dict)
    ownership_tag: dict[int, str] = field(default_factory=dict)
    country_type: dict[int, str] = field(default_factory=dict)
    province_tag_state: dict[int, tuple[str, str]] = field(default_factory=dict)
    hub_info: dict[int, dict[str, str]] = field(default_factory=dict)
    key_index: "ProvinceKeyIndex | None" = field(default=None, repr=False)

    def hub_display_labels(self) -> dict[int, str]:
        """Land provinces default to normal; hubs override. Sea stays unlabeled -> white."""
        labels = {key: "normal" for key, label in self.terrain.items() if label != "sea"}
        labels.update(self.hub)
        return labels


def load_static_map_base(conn: sqlite3.Connection) -> StaticMapBase:
    land_keys = load_land_province_keys(conn)
    sea_keys = load_sea_province_keys(conn)
    prime_keys = load_prime_land_keys(conn)
    impassable_keys = load_impassable_keys(conn)

    terrain: dict[int, str] = {}
    for key in sea_keys:
        terrain[key] = "sea"
    for key in land_keys:
        if key in impassable_keys:
            terrain[key] = "impassable"
        elif key in prime_keys:
            terrain[key] = "prime"
        else:
            terrain[key] = "normal"

    hub_info = load_hub_provinces(conn)
    hub = {key: info["hub_type"] for key, info in hub_info.items()}
    return StaticMapBase(
        terrain=terrain,
        hub=hub,
        hub_info=hub_info,
        province_geographic_state=load_province_geographic_state(conn),
    )


def load_scenario_overlay(conn: sqlite3.Connection) -> ScenarioOverlay:
    tag_state_types = load_tag_state_types(conn)
    tag_country_types = load_tag_country_types(conn)
    province_tag_state = load_province_tag_state(conn)
    ownership_tag: dict[int, str] = {}
    incorporation: dict[int, str] = {}
    country_type: dict[int, str] = {}
    for prov_key, (tag, state) in province_tag_state.items():
        ownership_tag[prov_key] = tag
        if tag_state_types.get((tag, state), "incorporated") == "unincorporated":
            incorporation[prov_key] = "unincorporated"
        else:
            incorporation[prov_key] = "incorporated"
        country_type[prov_key] = tag_country_types.get(tag, "recognized")
    return ScenarioOverlay(
        ownership_tag=ownership_tag,
        incorporation=incorporation,
        country_type=country_type,
        province_tag_state=province_tag_state,
    )


def merge_province_model(
    rgb_keys: np.ndarray,
    static: StaticMapBase,
    scenario: ScenarioOverlay,
    *,
    key_index: "ProvinceKeyIndex | None" = None,
) -> ProvinceModel:
    return ProvinceModel(
        rgb_keys=rgb_keys,
        terrain=static.terrain,
        hub=static.hub,
        hub_info=static.hub_info,
        incorporation=scenario.incorporation,
        ownership_tag=scenario.ownership_tag,
        country_type=scenario.country_type,
        province_tag_state=scenario.province_tag_state,
        key_index=key_index,
    )


def load_province_model(
    conn: sqlite3.Connection,
    png_bytes: bytes | None = None,
    *,
    rgb_keys: np.ndarray | None = None,
) -> ProvinceModel:
    if rgb_keys is None:
        if png_bytes is None:
            raise ValueError("load_province_model 需要 png_bytes 或 rgb_keys")
        rgb_keys, _ = province_rgb_keys_from_bytes(png_bytes)
    static = load_static_map_base(conn)
    scenario = load_scenario_overlay(conn)
    return merge_province_model(rgb_keys, static, scenario)
