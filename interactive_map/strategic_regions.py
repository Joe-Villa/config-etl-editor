"""Strategic region map layer from ref_strat + geographic state regions."""

from __future__ import annotations

import sqlite3

from interactive_map.compositor import render_palette_png_bytes
from interactive_map.db_reader import load_province_geographic_state
from interactive_map.png_util import key_to_hex
from interactive_map.province_model import ProvinceModel


def normalize_map_color_component(value: float) -> int:
    if value <= 1.0:
        return int(round(value * 255))
    return int(round(value))


def load_strategic_region_palette(
    conn: sqlite3.Connection,
) -> dict[str, tuple[int, int, int]]:
    palette: dict[str, tuple[int, int, int]] = {}
    for region, map_r, map_g, map_b in conn.execute(
        "SELECT region, map_r, map_g, map_b FROM ref_strat ORDER BY region"
    ):
        palette[str(region)] = (
            normalize_map_color_component(float(map_r)),
            normalize_map_color_component(float(map_g)),
            normalize_map_color_component(float(map_b)),
        )
    return palette


def load_state_to_strategic_region(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(state): str(region)
        for region, state in conn.execute(
            "SELECT region, state FROM ref_strat_st ORDER BY region, state"
        )
    }


def load_province_strategic_region(conn: sqlite3.Connection) -> dict[int, str]:
    state_region = load_state_to_strategic_region(conn)
    labels: dict[int, str] = {}
    for prov_key, geo_state in load_province_geographic_state(conn).items():
        region = state_region.get(geo_state)
        if region is not None:
            labels[prov_key] = region
    return labels


def load_strategic_regions_json(conn: sqlite3.Connection) -> dict:
    palette = load_strategic_region_palette(conn)
    state_region = load_state_to_strategic_region(conn)
    province_state = {
        key_to_hex(key): state
        for key, state in load_province_geographic_state(conn).items()
    }
    return {
        "regions": {
            region: {"r": rgb[0], "g": rgb[1], "b": rgb[2]}
            for region, rgb in palette.items()
        },
        "state_region": state_region,
        "province_state": province_state,
    }


def render_strategic_region_png(model: ProvinceModel, conn: sqlite3.Connection) -> bytes:
    labels = load_province_strategic_region(conn)
    palette = load_strategic_region_palette(conn)
    png_bytes, _, _ = render_palette_png_bytes(model, labels, palette)
    return png_bytes
