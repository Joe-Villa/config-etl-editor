"""Incorporation status layer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from interactive_map.compositor import render_palette_layer, render_palette_png_bytes
from interactive_map.db_reader import load_tag_state_types
from interactive_map.palette import INCORPORATION_PALETTE
from interactive_map.province_model import ProvinceModel, load_province_model


def incorporation_counts(model: ProvinceModel) -> tuple[int, int]:
    inc = sum(1 for label in model.incorporation.values() if label == "incorporated")
    uninc = sum(1 for label in model.incorporation.values() if label == "unincorporated")
    return inc, uninc


def render_incorporation_png(model: ProvinceModel) -> bytes:
    png_bytes, _, _ = render_palette_png_bytes(
        model, model.incorporation, INCORPORATION_PALETTE
    )
    return png_bytes


def build_incorporation_json(conn: sqlite3.Connection) -> dict:
    tag_state_types = load_tag_state_types(conn)
    return {
        "incorporated_tag_states": sum(
            1 for state_type in tag_state_types.values() if state_type == "incorporated"
        ),
        "unincorporated_tag_states": sum(
            1
            for state_type in tag_state_types.values()
            if state_type == "unincorporated"
        ),
        "colors": {name: list(rgb) for name, rgb in INCORPORATION_PALETTE.items()},
    }


def generate_incorporation_layer(
    png_bytes: bytes,
    conn: sqlite3.Connection,
    output_dir: Path,
    *,
    model: ProvinceModel | None = None,
) -> tuple[int, int]:
    province_model = model or load_province_model(conn, png_bytes)
    output_dir.mkdir(parents=True, exist_ok=True)
    render_palette_layer(
        province_model,
        province_model.incorporation,
        INCORPORATION_PALETTE,
        output_dir / "incorporation.png",
    )
    (output_dir / "incorporation.json").write_text(
        json.dumps(build_incorporation_json(conn), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return incorporation_counts(province_model)
