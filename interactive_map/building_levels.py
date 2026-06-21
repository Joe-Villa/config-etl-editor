"""Total building levels per tag+state scope (dynamic layer)."""

from __future__ import annotations

import sqlite3

from interactive_map.compositor import render_palette_png_bytes
from interactive_map.foreign_investment import scope_key
from interactive_map.palette import UNCOLORED_RGB
from interactive_map.province_model import ProvinceModel

# Light mint → dark green; level 1 is visibly colored (not white).
MIN_BUILDING_LEVEL_RGB = (210, 235, 200)
MAX_BUILDING_LEVEL_RGB = (45, 95, 55)


def compute_building_levels_by_scope(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], int]:
    """Sum all ownership slice levels for buildings in each (tag, state) scope."""
    return {
        (str(tag), str(state)): int(total or 0)
        for tag, state, total in conn.execute(
            """
            SELECT b.tag, b.state, SUM(o.level)
            FROM st_bld b
            JOIN st_bld_own o ON o.bld_id = b.id
            GROUP BY b.tag, b.state
            """
        )
    }


def level_to_rgb(level: int, max_level: int) -> tuple[int, int, int]:
    if level <= 0:
        return UNCOLORED_RGB
    cap = max(max_level, 1)
    if cap == 1:
        return MIN_BUILDING_LEVEL_RGB
    t = (level - 1) / (cap - 1)
    return tuple(
        int(
            MIN_BUILDING_LEVEL_RGB[i]
            + t * (MAX_BUILDING_LEVEL_RGB[i] - MIN_BUILDING_LEVEL_RGB[i])
        )
        for i in range(3)
    )


def build_building_level_palette(max_level: int) -> dict[str, tuple[int, int, int]]:
    palette = {
        "sea": UNCOLORED_RGB,
        "unowned": UNCOLORED_RGB,
    }
    for level in range(1, max(max_level, 1) + 1):
        palette[str(level)] = level_to_rgb(level, max(max_level, 1))
    return palette


def build_province_building_level_labels(
    province_tag_state: dict[int, tuple[str, str]],
    levels_by_scope: dict[tuple[str, str], int],
) -> dict[int, str]:
    labels: dict[int, str] = {}
    for prov_key, (tag, state) in province_tag_state.items():
        level = levels_by_scope.get((tag, state), 0)
        if level > 0:
            labels[prov_key] = str(level)
    return labels


def render_building_level_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> bytes:
    levels = compute_building_levels_by_scope(conn)
    max_level = max(levels.values(), default=0)
    tag_state = province_tag_state if province_tag_state is not None else model.province_tag_state
    labels = build_province_building_level_labels(tag_state, levels)
    palette = build_building_level_palette(max_level)
    png_bytes, _, _ = render_palette_png_bytes(model, labels, palette)
    return png_bytes


def build_building_level_json(
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> dict:
    levels = compute_building_levels_by_scope(conn)
    max_level = max(levels.values(), default=0)
    by_scope = {
        scope_key(tag, state): level
        for (tag, state), level in sorted(levels.items())
        if level > 0
    }
    legend_levels: list[int] = [0]
    if max_level > 0:
        for candidate in (
            1,
            max(2, max_level // 3),
            max(3, (2 * max_level) // 3),
            max_level,
        ):
            if candidate not in legend_levels:
                legend_levels.append(candidate)
        legend_levels.sort()
    legend = [
        {"level": level, "rgb": list(level_to_rgb(level, max(max_level, 1)))}
        for level in legend_levels
    ]
    scopes_with_buildings = len(by_scope)
    total_levels = sum(levels.values())
    if province_tag_state is not None:
        painted_scopes = {
            scope_key(tag, state)
            for _key, (tag, state) in province_tag_state.items()
            if levels.get((tag, state), 0) > 0
        }
        scopes_with_buildings = len(painted_scopes)
    return {
        "by_scope": by_scope,
        "max_level": max_level,
        "scopes_with_buildings": scopes_with_buildings,
        "total_levels": total_levels,
        "legend": legend,
    }
