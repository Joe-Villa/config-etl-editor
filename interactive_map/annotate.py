"""Terrain layer: data labels from ProvinceModel, colors from palette."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from interactive_map.compositor import render_palette_layer, render_palette_png_bytes
from interactive_map.palette import TERRAIN_PALETTE
from interactive_map.png_util import key_to_hex
from interactive_map.province_model import ProvinceModel, load_province_model


def build_terrain_json(model: ProvinceModel) -> dict:
    prime_keys = {k for k, v in model.terrain.items() if v == "prime"}
    impassable_keys = {k for k, v in model.terrain.items() if v == "impassable"}
    return {
        "prime_land": sorted(key_to_hex(k) for k in prime_keys),
        "impassable": sorted(key_to_hex(k) for k in impassable_keys),
        "colors": {name: list(rgb) for name, rgb in TERRAIN_PALETTE.items()},
    }


def terrain_counts(model: ProvinceModel) -> tuple[int, int, int]:
    prime = sum(1 for v in model.terrain.values() if v == "prime")
    normal = sum(1 for v in model.terrain.values() if v == "normal")
    impassable = sum(1 for v in model.terrain.values() if v == "impassable")
    return prime, normal, impassable


def render_terrain_png(model: ProvinceModel) -> bytes:
    png_bytes, _, _ = render_palette_png_bytes(model, model.terrain, TERRAIN_PALETTE)
    return png_bytes


def generate_terrain_layers(
    png_bytes: bytes,
    conn: sqlite3.Connection,
    output_dir: Path,
    *,
    model: ProvinceModel | None = None,
) -> tuple[int, int, int]:
    province_model = model or load_province_model(conn, png_bytes)
    output_dir.mkdir(parents=True, exist_ok=True)
    render_palette_layer(
        province_model,
        province_model.terrain,
        TERRAIN_PALETTE,
        output_dir / "terrain.png",
    )
    (output_dir / "terrain.json").write_text(
        json.dumps(build_terrain_json(province_model), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return terrain_counts(province_model)
