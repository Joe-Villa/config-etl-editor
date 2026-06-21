"""Foreign-owned building levels per tag+state scope (dynamic layer)."""

from __future__ import annotations

import sqlite3

from interactive_map.compositor import render_palette_png_bytes
from interactive_map.edit.buildings import resolve_owner_tag_for_export
from interactive_map.palette import UNCOLORED_RGB
from interactive_map.province_model import ProvinceModel

# Level 1 is deliberately not white; higher levels darken toward MAX.
MIN_FOREIGN_RGB = (255, 200, 140)
MAX_FOREIGN_RGB = (140, 45, 15)


def scope_key(tag: str, state: str) -> str:
    return f"{tag}::{state}"


def compute_foreign_by_scope(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    """Sum foreign ownership levels per (scope_tag, state).

    A slice counts as foreign when its resolved owner_tag differs from st_bld.tag.
    """
    totals: dict[tuple[str, str], int] = {}
    for bld_id, state, scope_tag in conn.execute(
        "SELECT id, state, tag FROM st_bld"
    ):
        scope_tag = str(scope_tag)
        state = str(state)
        for level, owner_tag in conn.execute(
            """
            SELECT level, owner_tag
            FROM st_bld_own
            WHERE bld_id = ?
            ORDER BY ord
            """,
            (int(bld_id),),
        ):
            effective = resolve_owner_tag_for_export(scope_tag, str(owner_tag))
            if effective != scope_tag:
                key = (scope_tag, state)
                totals[key] = totals.get(key, 0) + int(level)
    return totals


def level_to_rgb(level: int, max_level: int) -> tuple[int, int, int]:
    if level <= 0:
        return UNCOLORED_RGB
    cap = max(max_level, 1)
    if cap == 1:
        return MIN_FOREIGN_RGB
    t = (level - 1) / (cap - 1)
    return tuple(
        int(MIN_FOREIGN_RGB[i] + t * (MAX_FOREIGN_RGB[i] - MIN_FOREIGN_RGB[i]))
        for i in range(3)
    )


def build_foreign_palette(max_level: int) -> dict[str, tuple[int, int, int]]:
    palette = {
        "sea": UNCOLORED_RGB,
        "unowned": UNCOLORED_RGB,
    }
    for level in range(1, max(max_level, 1) + 1):
        palette[str(level)] = level_to_rgb(level, max(max_level, 1))
    return palette


def build_province_foreign_labels(
    province_tag_state: dict[int, tuple[str, str]],
    foreign_by_scope: dict[tuple[str, str], int],
) -> dict[int, str]:
    labels: dict[int, str] = {}
    for prov_key, (tag, state) in province_tag_state.items():
        level = foreign_by_scope.get((tag, state), 0)
        if level > 0:
            labels[prov_key] = str(level)
    return labels


def render_foreign_investment_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> bytes:
    foreign = compute_foreign_by_scope(conn)
    max_level = max(foreign.values(), default=0)
    tag_state = province_tag_state if province_tag_state is not None else model.province_tag_state
    labels = build_province_foreign_labels(tag_state, foreign)
    palette = build_foreign_palette(max_level)
    png_bytes, _, _ = render_palette_png_bytes(model, labels, palette)
    return png_bytes


def build_foreign_investment_json(
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> dict:
    foreign = compute_foreign_by_scope(conn)
    max_level = max(foreign.values(), default=0)
    by_scope = {
        scope_key(tag, state): level
        for (tag, state), level in sorted(foreign.items())
        if level > 0
    }
    legend_levels: list[int] = [0]
    if max_level > 0:
        for candidate in (1, max(2, max_level // 3), max(3, (2 * max_level) // 3), max_level):
            if candidate not in legend_levels:
                legend_levels.append(candidate)
        legend_levels.sort()
    legend = [
        {"level": level, "rgb": list(level_to_rgb(level, max(max_level, 1)))}
        for level in legend_levels
    ]
    scopes_with_foreign = len(by_scope)
    total_foreign_level = sum(foreign.values())
    if province_tag_state is not None:
        painted_scopes = {
            scope_key(tag, state)
            for _key, (tag, state) in province_tag_state.items()
            if foreign.get((tag, state), 0) > 0
        }
        scopes_with_foreign = len(painted_scopes)
    return {
        "by_scope": by_scope,
        "max_level": max_level,
        "scopes_with_foreign": scopes_with_foreign,
        "total_foreign_level": total_foreign_level,
        "legend": legend,
    }
