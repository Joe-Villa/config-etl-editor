"""Ownership layer: tag labels from ProvinceModel, tag colors from ref_tag."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from interactive_map.compositor import render_palette_layer, render_palette_png_bytes
from interactive_map.db_reader import load_country_colors
from interactive_map.province_model import ProvinceModel, load_province_model


def adjust_color_for_white_bg(
    color: tuple[int, int, int],
    *,
    bg: tuple[int, int, int] = (255, 255, 255),
    min_channel_gap: int = 50,
) -> tuple[int, int, int]:
    r, g, b = color
    br, bg_c, bb = bg
    gaps = (br - r, bg_c - g, bb - b)
    if min(gaps) >= min_channel_gap:
        return color
    scale = min(
        (br - min_channel_gap) / r if r else 1.0,
        (bg_c - min_channel_gap) / g if g else 1.0,
        (bb - min_channel_gap) / b if b else 1.0,
        1.0,
    )
    return (
        max(0, int(r * scale)),
        max(0, int(g * scale)),
        max(0, int(b * scale)),
    )


def build_ownership_palette(
    conn: sqlite3.Connection,
) -> dict[str, tuple[int, int, int]]:
    return {
        tag: adjust_color_for_white_bg(color)
        for tag, color in load_country_colors(conn).items()
    }


def render_ownership_png(model: ProvinceModel, conn: sqlite3.Connection) -> tuple[bytes, int, int]:
    palette = build_ownership_palette(conn)
    return render_palette_png_bytes(model, model.ownership_tag, palette)


def generate_ownership_map(
    png_bytes: bytes,
    conn: sqlite3.Connection,
    output_path: Path,
    *,
    model: ProvinceModel | None = None,
) -> tuple[int, int]:
    province_model = model or load_province_model(conn, png_bytes)
    palette = build_ownership_palette(conn)
    return render_palette_layer(
        province_model,
        province_model.ownership_tag,
        palette,
        output_path,
    )
