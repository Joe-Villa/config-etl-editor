"""Dynamic population map layers: slavery presence and total population."""

from __future__ import annotations

import sqlite3

from interactive_map.compositor import render_palette_png_bytes
from interactive_map.foreign_investment import scope_key
from interactive_map.palette import (
    POP_TOTAL_MAX_RGB,
    POP_TOTAL_ZERO_RGB,
    SLAVERY_MAX_RGB,
    SLAVERY_MIN_RGB,
    SLAVERY_NO_SLAVES_RGB,
    UNCOLORED_RGB,
)
from interactive_map.province_model import ProvinceModel


def compute_population_by_scope(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    return {
        (str(tag), str(state)): int(total or 0)
        for tag, state, total in conn.execute(
            """
            SELECT tag, state, SUM(size)
            FROM st_pop
            GROUP BY tag, state
            """
        )
    }


def compute_slave_pop_by_scope(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    return {
        (str(tag), str(state)): int(total or 0)
        for tag, state, total in conn.execute(
            """
            SELECT tag, state, SUM(size)
            FROM st_pop
            WHERE is_slaves = 1
            GROUP BY tag, state
            """
        )
    }


def compute_slavery_by_scope(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], dict[str, int | bool]]:
    """Per scope: whether any slave pops exist and total slave population."""
    return {
        key: {"has_slaves": pop > 0, "slave_pop": pop}
        for key, pop in compute_slave_pop_by_scope(conn).items()
    }


def slavery_pop_to_rgb(slave_pop: int, max_slave_pop: int) -> tuple[int, int, int]:
    if slave_pop <= 0:
        return SLAVERY_NO_SLAVES_RGB
    if max_slave_pop <= 0:
        return SLAVERY_MIN_RGB
    if max_slave_pop == 1:
        return SLAVERY_MAX_RGB
    t = (slave_pop - 1) / (max_slave_pop - 1)
    return tuple(
        int(SLAVERY_MIN_RGB[i] + t * (SLAVERY_MAX_RGB[i] - SLAVERY_MIN_RGB[i]))
        for i in range(3)
    )


def build_slavery_palette(slave_pops: dict[tuple[str, str], int]) -> dict[str, tuple[int, int, int]]:
    max_pop = max(slave_pops.values(), default=0)
    palette: dict[str, tuple[int, int, int]] = {
        "sea": UNCOLORED_RGB,
        "unowned": UNCOLORED_RGB,
        "0": SLAVERY_NO_SLAVES_RGB,
    }
    for pop in sorted(set(slave_pops.values())):
        if pop > 0:
            palette[str(pop)] = slavery_pop_to_rgb(pop, max_pop)
    return palette


def pop_total_to_rgb(population: int, max_population: int) -> tuple[int, int, int]:
    if population <= 0:
        return POP_TOTAL_ZERO_RGB
    if max_population <= 0:
        return POP_TOTAL_ZERO_RGB
    if max_population == 1:
        return POP_TOTAL_MAX_RGB
    t = population / max_population
    return tuple(
        int(POP_TOTAL_ZERO_RGB[i] + t * (POP_TOTAL_MAX_RGB[i] - POP_TOTAL_ZERO_RGB[i]))
        for i in range(3)
    )


def build_pop_total_palette(populations: dict[tuple[str, str], int]) -> dict[str, tuple[int, int, int]]:
    max_pop = max(populations.values(), default=0)
    palette: dict[str, tuple[int, int, int]] = {
        "sea": UNCOLORED_RGB,
        "unowned": UNCOLORED_RGB,
        "0": POP_TOTAL_ZERO_RGB,
    }
    for pop in sorted(set(populations.values())):
        if pop > 0:
            palette[str(pop)] = pop_total_to_rgb(pop, max_pop)
    return palette


def build_province_slavery_labels(
    province_tag_state: dict[int, tuple[str, str]],
    slave_pops: dict[tuple[str, str], int],
) -> dict[int, str]:
    labels: dict[int, str] = {}
    for prov_key, (tag, state) in province_tag_state.items():
        labels[prov_key] = str(slave_pops.get((tag, state), 0))
    return labels


def build_province_pop_total_labels(
    province_tag_state: dict[int, tuple[str, str]],
    populations: dict[tuple[str, str], int],
) -> dict[int, str]:
    labels: dict[int, str] = {}
    for prov_key, (tag, state) in province_tag_state.items():
        labels[prov_key] = str(populations.get((tag, state), 0))
    return labels


def render_slavery_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> bytes:
    tag_state = province_tag_state if province_tag_state is not None else model.province_tag_state
    slave_pops = compute_slave_pop_by_scope(conn)
    labels = build_province_slavery_labels(tag_state, slave_pops)
    palette = build_slavery_palette(slave_pops)
    png_bytes, _, _ = render_palette_png_bytes(model, labels, palette)
    return png_bytes


def render_pop_total_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> bytes:
    tag_state = province_tag_state if province_tag_state is not None else model.province_tag_state
    populations = compute_population_by_scope(conn)
    labels = build_province_pop_total_labels(tag_state, populations)
    palette = build_pop_total_palette(populations)
    png_bytes, _, _ = render_palette_png_bytes(model, labels, palette)
    return png_bytes


def build_slavery_json(
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> dict:
    slave_pops = compute_slave_pop_by_scope(conn)
    max_slave_pop = max(slave_pops.values(), default=0)
    by_scope = {
        scope_key(tag, state): {
            "has_slaves": pop > 0,
            "slave_pop": pop,
        }
        for (tag, state), pop in sorted(slave_pops.items())
    }
    scopes_with_slaves = sum(1 for pop in slave_pops.values() if pop > 0)
    if province_tag_state is not None:
        scopes_with_slaves = sum(
            1
            for tag, state in province_tag_state.values()
            if slave_pops.get((tag, state), 0) > 0
        )
    legend_levels: list[int] = [0]
    if max_slave_pop > 0:
        for candidate in (1, max(2, max_slave_pop // 4), max(3, max_slave_pop // 2), max_slave_pop):
            if candidate not in legend_levels:
                legend_levels.append(candidate)
        legend_levels.sort()
    legend = [
        {"slave_pop": pop, "rgb": list(slavery_pop_to_rgb(pop, max(max_slave_pop, 1)))}
        for pop in legend_levels
    ]
    return {
        "by_scope": by_scope,
        "max_slave_pop": max_slave_pop,
        "total_slave_pop": sum(slave_pops.values()),
        "scopes_with_slaves": scopes_with_slaves,
        "legend": legend,
    }


def build_pop_total_json(
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> dict:
    populations = compute_population_by_scope(conn)
    max_pop = max(populations.values(), default=0)
    by_scope = {
        scope_key(tag, state): pop
        for (tag, state), pop in sorted(populations.items())
    }
    legend_levels: list[int] = [0]
    if max_pop > 0:
        for candidate in (1, max(2, max_pop // 4), max(3, max_pop // 2), max_pop):
            if candidate not in legend_levels:
                legend_levels.append(candidate)
        legend_levels.sort()
    legend = [
        {"population": pop, "rgb": list(pop_total_to_rgb(pop, max(max_pop, 1)))}
        for pop in legend_levels
    ]
    return {
        "by_scope": by_scope,
        "max_population": max_pop,
        "total_population": sum(populations.values()),
        "legend": legend,
    }


POP_MIX_LAYER_NAMES = ("pop_culture", "pop_religion")


def mix_weighted_rgb(
    parts: list[tuple[tuple[int, int, int], int]],
) -> tuple[int, int, int]:
    total = sum(weight for _, weight in parts)
    if total <= 0:
        return UNCOLORED_RGB
    channels = [
        sum(color[i] * weight for color, weight in parts) / total for i in range(3)
    ]
    return tuple(int(round(channel)) for channel in channels)


def _group_pop_sizes(
    conn: sqlite3.Connection,
    *,
    dimension: str,
) -> dict[tuple[str, str], list[tuple[str, int]]]:
    if dimension == "culture":
        query = """
            SELECT tag, state, culture AS key, SUM(size) AS total
            FROM st_pop
            GROUP BY tag, state, culture
        """
    elif dimension == "religion":
        query = """
            SELECT p.tag, p.state,
                   COALESCE(p.religion, c.default_religion) AS key,
                   SUM(p.size) AS total
            FROM st_pop p
            JOIN ref_culture c ON c.culture = p.culture
            GROUP BY p.tag, p.state, key
        """
    else:
        raise ValueError(dimension)
    grouped: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for tag, state, key, total in conn.execute(query):
        if int(total or 0) <= 0:
            continue
        grouped.setdefault((str(tag), str(state)), []).append((str(key), int(total)))
    return grouped


def compute_pop_mix_by_scope(
    conn: sqlite3.Connection,
    *,
    dimension: str,
) -> dict[tuple[str, str], tuple[int, int, int]]:
    if dimension == "culture":
        colors = {
            str(culture): (int(r), int(g), int(b))
            for culture, r, g, b in conn.execute(
                "SELECT culture, r, g, b FROM ref_culture"
            )
        }
    elif dimension == "religion":
        try:
            color_rows = conn.execute(
                "SELECT religion, r, g, b FROM ref_religion"
            ).fetchall()
        except sqlite3.OperationalError:
            color_rows = [
                (religion, 255, 255, 255)
                for (religion,) in conn.execute("SELECT religion FROM ref_religion")
            ]
        colors = {
            str(religion): (int(r), int(g), int(b))
            for religion, r, g, b in color_rows
        }
    else:
        raise ValueError(dimension)

    mix: dict[tuple[str, str], tuple[int, int, int]] = {}
    for scope, entries in _group_pop_sizes(conn, dimension=dimension).items():
        parts = [
            (colors.get(key, UNCOLORED_RGB), size)
            for key, size in entries
            if size > 0
        ]
        if not parts:
            continue
        mix[scope] = mix_weighted_rgb(parts)
    return mix


def build_scope_pop_breakdown(
    conn: sqlite3.Connection,
    *,
    dimension: str,
) -> dict[tuple[str, str], dict]:
    grouped = _group_pop_sizes(conn, dimension=dimension)
    out: dict[tuple[str, str], dict] = {}
    for scope, entries in grouped.items():
        total = sum(size for _, size in entries)
        if total <= 0:
            continue
        breakdown = [
            {
                dimension: key,
                "size": size,
                "share": round(size / total, 4),
            }
            for key, size in sorted(entries, key=lambda item: (-item[1], item[0]))
        ]
        out[scope] = {
            "total": total,
            "breakdown": breakdown,
        }
    return out


def build_province_pop_mix_rgb(
    province_tag_state: dict[int, tuple[str, str]],
    mix_by_scope: dict[tuple[str, str], tuple[int, int, int]],
) -> dict[int, tuple[int, int, int]]:
    return {
        prov_key: rgb
        for prov_key, (tag, state) in province_tag_state.items()
        if (rgb := mix_by_scope.get((tag, state))) is not None
    }


def render_pop_mix_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    dimension: str,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> bytes:
    from interactive_map.compositor import render_direct_rgb_png_bytes

    tag_state = province_tag_state if province_tag_state is not None else model.province_tag_state
    mix_by_scope = compute_pop_mix_by_scope(conn, dimension=dimension)
    rgb_by_key = build_province_pop_mix_rgb(tag_state, mix_by_scope)
    png_bytes, _, _ = render_direct_rgb_png_bytes(model, rgb_by_key)
    return png_bytes


def build_pop_mix_json(
    conn: sqlite3.Connection,
    *,
    dimension: str,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> dict:
    mix_by_scope = compute_pop_mix_by_scope(conn, dimension=dimension)
    breakdown_by_scope = build_scope_pop_breakdown(conn, dimension=dimension)
    by_scope: dict[str, dict] = {}
    for (tag, state), rgb in sorted(mix_by_scope.items()):
        key = scope_key(tag, state)
        entry = breakdown_by_scope.get((tag, state), {"total": 0, "breakdown": []})
        by_scope[key] = {
            "rgb": list(rgb),
            "total": entry["total"],
            "breakdown": entry["breakdown"],
        }
    scopes_with_population = len(by_scope)
    if province_tag_state is not None:
        scopes_with_population = sum(
            1
            for tag, state in province_tag_state.values()
            if (tag, state) in mix_by_scope
        )
    return {
        "dimension": dimension,
        "by_scope": by_scope,
        "scopes_with_population": scopes_with_population,
        "total_population": sum(item["total"] for item in breakdown_by_scope.values()),
    }


def render_pop_culture_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> bytes:
    return render_pop_mix_png(
        model,
        conn,
        dimension="culture",
        province_tag_state=province_tag_state,
    )


def render_pop_religion_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> bytes:
    return render_pop_mix_png(
        model,
        conn,
        dimension="religion",
        province_tag_state=province_tag_state,
    )


def build_pop_culture_json(
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> dict:
    return build_pop_mix_json(
        conn,
        dimension="culture",
        province_tag_state=province_tag_state,
    )


def build_pop_religion_json(
    conn: sqlite3.Connection,
    *,
    province_tag_state: dict[int, tuple[str, str]] | None = None,
) -> dict:
    return build_pop_mix_json(
        conn,
        dimension="religion",
        province_tag_state=province_tag_state,
    )
