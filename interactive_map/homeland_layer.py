"""Cultural homeland layer: color geographic states by ``geo_homeland``."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from interactive_map.compositor import render_palette_png_bytes
from interactive_map.db_reader import load_culture_colors, load_province_geographic_state
from interactive_map.palette import (
    HOMELAND_MULTI_RGB,
    HOMELAND_NONE_RGB,
    UNCOLORED_RGB,
)
from interactive_map.province_model import ProvinceModel

HOMELAND_LABEL_NONE = "none"
HOMELAND_LABEL_MULTI = "multi"
HOMELAND_LABEL_SEA = "sea"


def load_state_homelands(conn: sqlite3.Connection) -> dict[str, list[str]]:
    by_state: dict[str, list[str]] = defaultdict(list)
    for state, culture in conn.execute(
        "SELECT state, culture FROM geo_homeland ORDER BY state, culture"
    ):
        by_state[str(state)].append(str(culture))
    return dict(by_state)


def build_homeland_palette(conn: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    palette: dict[str, tuple[int, int, int]] = {
        HOMELAND_LABEL_SEA: UNCOLORED_RGB,
        HOMELAND_LABEL_NONE: HOMELAND_NONE_RGB,
        HOMELAND_LABEL_MULTI: HOMELAND_MULTI_RGB,
    }
    palette.update(load_culture_colors(conn))
    return palette


def build_homeland_labels(
    model: ProvinceModel,
    province_geographic_state: dict[int, str],
    state_homelands: dict[str, list[str]],
) -> dict[int, str]:
    labels: dict[int, str] = {}
    for key, terrain in model.terrain.items():
        if terrain == "sea":
            labels[key] = HOMELAND_LABEL_SEA
            continue
        geo_state = province_geographic_state.get(key)
        if not geo_state:
            labels[key] = HOMELAND_LABEL_NONE
            continue
        homelands = state_homelands.get(geo_state, [])
        if not homelands:
            labels[key] = HOMELAND_LABEL_NONE
        elif len(homelands) == 1:
            labels[key] = homelands[0]
        else:
            labels[key] = HOMELAND_LABEL_MULTI
    return labels


def render_homeland_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    province_geographic_state: dict[int, str] | None = None,
) -> bytes:
    if province_geographic_state is None:
        province_geographic_state = load_province_geographic_state(conn)
    state_homelands = load_state_homelands(conn)
    labels = build_homeland_labels(model, province_geographic_state, state_homelands)
    palette = build_homeland_palette(conn)
    png_bytes, _, _ = render_palette_png_bytes(model, labels, palette)
    return png_bytes


def build_homeland_json(conn: sqlite3.Connection) -> dict:
    state_homelands = load_state_homelands(conn)
    all_geo_states = {
        str(row[0]) for row in conn.execute("SELECT state FROM geo_state")
    }
    states_with_homeland = set(state_homelands)
    return {
        "state_homelands": state_homelands,
        "colors": {
            "none": list(HOMELAND_NONE_RGB),
            "multi": list(HOMELAND_MULTI_RGB),
        },
        "stats": {
            "single_culture_states": sum(
                1 for homelands in state_homelands.values() if len(homelands) == 1
            ),
            "multi_culture_states": sum(
                1 for homelands in state_homelands.values() if len(homelands) > 1
            ),
            "no_homeland_states": len(all_geo_states - states_with_homeland),
        },
    }
