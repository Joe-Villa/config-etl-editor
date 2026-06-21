"""Province map pixel helpers."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def province_rgb_keys_from_bytes(png_bytes: bytes) -> tuple[np.ndarray, tuple[int, int]]:
    """Parse provinces.png pixels from raw bytes (e.g. map_png BLOB)."""
    Image.MAX_IMAGE_PIXELS = None
    province_img = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
    h, w, _ = province_img.shape
    rgb_keys = (
        province_img[:, :, 0].astype(np.uint32) << 16
        | province_img[:, :, 1].astype(np.uint32) << 8
        | province_img[:, :, 2].astype(np.uint32)
    )
    return rgb_keys, (w, h)


def png_size(png_bytes: bytes) -> tuple[int, int]:
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(io.BytesIO(png_bytes)) as img:
        return img.size


def province_hex_to_key(province_hex: str) -> int:
    value = province_hex.strip()
    if value[:1].lower() == "x" or value.startswith("#"):
        value = value[1:]
    return (
        int(value[0:2], 16) << 16
        | int(value[2:4], 16) << 8
        | int(value[4:6], 16)
    )


def normalize_province_db(province: str) -> str:
    """Return canonical DB province key ``xRRGGBB`` (matches ``util.norm_province``)."""
    text = str(province).strip()
    if text.lower().startswith("x"):
        hexpart = text[1:]
    elif text.startswith("#"):
        hexpart = text[1:]
    elif len(text) == 6:
        hexpart = text
    else:
        raise ValueError(f"无效地块颜色：{province}")
    if len(hexpart) != 6:
        raise ValueError(f"无效地块颜色：{province}")
    try:
        int(hexpart, 16)
    except ValueError as exc:
        raise ValueError(f"无效地块颜色：{province}") from exc
    return "x" + hexpart.upper()


def province_db_to_hex(province: str) -> str:
    """Display form ``#rrggbb`` for UI / map click keys."""
    return "#" + normalize_province_db(province)[1:].lower()


def key_to_hex(key: int) -> str:
    r = (key >> 16) & 0xFF
    g = (key >> 8) & 0xFF
    b = key & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"
