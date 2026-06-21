"""Country type layer: province colors by owner tag's country_type."""

from __future__ import annotations

import sqlite3

from interactive_map.compositor import render_palette_png_bytes
from interactive_map.db_reader import load_tag_country_types
from interactive_map.palette import (
    COUNTRY_TYPE_PALETTE,
    VANILLA_COUNTRY_TYPES,
)
from interactive_map.province_model import ProvinceModel


def country_type_render_key(raw_type: str) -> str:
    raw_type = str(raw_type or "recognized")
    return raw_type if raw_type in VANILLA_COUNTRY_TYPES else "custom"


def build_country_type_labels(
    model: ProvinceModel,
    tag_country_types: dict[str, str],
) -> dict[int, str]:
    labels: dict[int, str] = {}
    for key, tag in model.ownership_tag.items():
        raw = tag_country_types.get(tag, "recognized")
        labels[key] = country_type_render_key(raw)
    return labels


def render_country_type_png(
    model: ProvinceModel,
    tag_country_types: dict[str, str],
) -> bytes:
    labels = build_country_type_labels(model, tag_country_types)
    png_bytes, _, _ = render_palette_png_bytes(
        model, labels, COUNTRY_TYPE_PALETTE
    )
    return png_bytes


def build_country_type_json(conn: sqlite3.Connection) -> dict:
    tag_country_types = load_tag_country_types(conn)
    custom_types = sorted(
        {
            country_type
            for country_type in tag_country_types.values()
            if country_type not in VANILLA_COUNTRY_TYPES
        }
    )
    by_type = {name: 0 for name in COUNTRY_TYPE_PALETTE if name not in ("sea", "unowned")}
    for country_type in tag_country_types.values():
        key = country_type_render_key(country_type)
        by_type[key] = by_type.get(key, 0) + 1
    return {
        "vanilla_types": sorted(VANILLA_COUNTRY_TYPES),
        "custom_types": custom_types,
        "tag_count_by_render_key": by_type,
        "colors": {name: list(rgb) for name, rgb in COUNTRY_TYPE_PALETTE.items()},
    }
