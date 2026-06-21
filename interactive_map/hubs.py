"""Hub provinces layer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from interactive_map.compositor import render_palette_layer, render_palette_png_bytes
from interactive_map.palette import HUB_PALETTE, HUB_TYPE_ZH
from interactive_map.png_util import key_to_hex
from interactive_map.province_model import ProvinceModel, load_province_model


def build_hubs_json(model: ProvinceModel) -> dict:
    by_type = {hub: 0 for hub in ("city", "port", "farm", "mine", "wood")}
    for hub_type in model.hub.values():
        by_type[hub_type] = by_type.get(hub_type, 0) + 1
    hubs_json = {key_to_hex(key): info for key, info in model.hub_info.items()}
    meta = {
        "hub_count": len(model.hub_info),
        "by_type": by_type,
        "colors": {name: list(rgb) for name, rgb in HUB_PALETTE.items()},
        "hub_type_zh": HUB_TYPE_ZH,
    }
    return {"provinces": hubs_json, "meta": meta}


def render_hubs_png(model: ProvinceModel) -> bytes:
    png_bytes, _, _ = render_palette_png_bytes(
        model, model.hub_display_labels(), HUB_PALETTE
    )
    return png_bytes


def generate_hubs_layer(
    png_bytes: bytes,
    conn: sqlite3.Connection,
    output_dir: Path,
    *,
    model: ProvinceModel | None = None,
) -> int:
    province_model = model or load_province_model(conn, png_bytes)
    output_dir.mkdir(parents=True, exist_ok=True)
    render_palette_layer(
        province_model,
        province_model.hub_display_labels(),
        HUB_PALETTE,
        output_dir / "hubs.png",
    )
    (output_dir / "hubs.json").write_text(
        json.dumps(build_hubs_json(province_model), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return len(province_model.hub_info)
