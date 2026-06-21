"""Bake immutable map assets into sqlite at database build time."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from interactive_map.annotate import terrain_counts
from interactive_map.borders import (
    render_static_border_province_png,
    render_static_border_state_png,
)
from interactive_map.compositor import (
    ProvinceKeyIndex,
    province_key_index,
    render_palette_png_bytes_indexed,
)
from interactive_map.db_reader import load_names_json, load_provinces_png_bytes
from interactive_map.palette import HUB_PALETTE, TERRAIN_PALETTE
from interactive_map.png_util import province_rgb_keys_from_bytes
from interactive_map.province_model import (
    ProvinceModel,
    ScenarioOverlay,
    StaticMapBase,
    load_static_map_base,
    merge_province_model,
)
from interactive_map.strategic_regions import (
    load_province_strategic_region,
    load_strategic_region_palette,
)

STATIC_LAYER_NAMES = (
    "terrain",
    "hubs",
    "strategic_region",
    "border_state",
    "border_province",
)

STATIC_LAYER_LABELS_ZH: dict[str, str] = {
    "terrain": "地块标注",
    "hubs": "枢纽",
    "strategic_region": "战略区域",
    "border_state": "州界",
    "border_province": "地块界",
}

StaticLayerProgressFn = Callable[[str, int, int], None]

STATIC_META_KEYS = (
    "map_width",
    "map_height",
    "total_pixels",
    "prime_land_count",
    "normal_land_count",
    "impassable_count",
    "hub_provinces",
    "tag_name_count",
    "state_name_count",
    "hub_name_count",
    "culture_name_count",
    "religion_name_count",
    "building_name_count",
    "building_group_name_count",
    "pm_name_count",
    "company_name_count",
)

# Static bake runs once per database build; skip PIL's slow PNG recompression pass.
_STATIC_PNG_OPTIMIZE = False


@dataclass(frozen=True)
class StaticRasterContext:
    """Single decode of provinces.png + one np.unique; shared by all static layers."""

    png_bytes: bytes
    rgb_keys: np.ndarray
    map_size: tuple[int, int]
    key_index: ProvinceKeyIndex
    model: ProvinceModel
    static: StaticMapBase


def load_static_raster_context(conn: sqlite3.Connection) -> StaticRasterContext:
    png_bytes = load_provinces_png_bytes(conn)
    rgb_keys, map_size = province_rgb_keys_from_bytes(png_bytes)
    static = load_static_map_base(conn)
    model = merge_province_model(rgb_keys, static, ScenarioOverlay())
    return StaticRasterContext(
        png_bytes=png_bytes,
        rgb_keys=rgb_keys,
        map_size=map_size,
        key_index=province_key_index(rgb_keys),
        model=model,
        static=static,
    )


def bake_static_layers(
    ctx: StaticRasterContext,
    conn: sqlite3.Connection,
    *,
    on_layer_progress: StaticLayerProgressFn | None = None,
) -> dict[str, bytes]:
    """Render layers that depend only on geographic reference data."""
    index = ctx.key_index
    model = ctx.model
    optimize = _STATIC_PNG_OPTIMIZE
    strategic_labels = load_province_strategic_region(conn)
    strategic_palette = load_strategic_region_palette(conn)
    total = len(STATIC_LAYER_NAMES)
    layers: dict[str, bytes] = {}

    def _step(key: str, render) -> None:
        label = STATIC_LAYER_LABELS_ZH[key]
        if on_layer_progress is not None and not layers:
            on_layer_progress(label, 0, total)
        layers[key] = render()
        if on_layer_progress is not None:
            on_layer_progress(label, len(layers), total)

    _step(
        "terrain",
        lambda: render_palette_png_bytes_indexed(
            index, model.terrain, TERRAIN_PALETTE, optimize=optimize
        )[0],
    )
    _step(
        "hubs",
        lambda: render_palette_png_bytes_indexed(
            index, model.hub_display_labels(), HUB_PALETTE, optimize=optimize
        )[0],
    )
    _step(
        "strategic_region",
        lambda: render_palette_png_bytes_indexed(
            index, strategic_labels, strategic_palette, optimize=optimize
        )[0],
    )
    _step(
        "border_state",
        lambda: render_static_border_state_png(
            ctx.rgb_keys,
            index,
            ctx.static.province_geographic_state,
            optimize=optimize,
        ),
    )
    _step(
        "border_province",
        lambda: render_static_border_province_png(ctx.rgb_keys, optimize=optimize),
    )
    return layers


def bake_static_meta(
    ctx: StaticRasterContext,
    conn: sqlite3.Connection,
) -> dict[str, str]:
    width, height = ctx.map_size
    prime, normal, impassable = terrain_counts(ctx.model)
    names = load_names_json(conn, locale="zh")
    return {
        "map_width": str(width),
        "map_height": str(height),
        "total_pixels": str(ctx.key_index.total_pixels),
        "prime_land_count": str(prime),
        "normal_land_count": str(normal),
        "impassable_count": str(impassable),
        "hub_provinces": str(len(ctx.static.hub_info)),
        "tag_name_count": str(len(names["tags"])),
        "state_name_count": str(len(names["states"])),
        "hub_name_count": str(len(names["hubs"])),
        "culture_name_count": str(len(names["cultures"])),
        "religion_name_count": str(len(names["religions"])),
        "building_name_count": str(len(names["buildings"])),
        "building_group_name_count": str(len(names["building_groups"])),
        "pm_name_count": str(len(names["pms"])),
        "company_name_count": str(len(names["companies"])),
    }


def insert_static_assets(
    conn: sqlite3.Connection,
    *,
    on_layer_progress: StaticLayerProgressFn | None = None,
) -> None:
    ctx = load_static_raster_context(conn)
    for layer, png in bake_static_layers(
        ctx, conn, on_layer_progress=on_layer_progress
    ).items():
        conn.execute(
            "INSERT INTO map_layer_png (layer, png) VALUES (?, ?)",
            (layer, png),
        )
    for key, value in bake_static_meta(ctx, conn).items():
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            (key, value),
        )
