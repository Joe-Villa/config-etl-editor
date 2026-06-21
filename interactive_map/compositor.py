"""Unified raster compositor: semantic label + display palette -> PNG."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from interactive_map.palette import UNCOLORED_RGB
from interactive_map.province_model import ProvinceModel


@dataclass(frozen=True)
class ProvinceKeyIndex:
    """One np.unique pass over provinces.png pixels; reused by every static layer."""

    unique_keys: np.ndarray
    inverse: np.ndarray
    counts: np.ndarray
    shape: tuple[int, ...]

    @property
    def total_pixels(self) -> int:
        return int(self.inverse.size)


def province_key_index(rgb_keys: np.ndarray) -> ProvinceKeyIndex:
    flat_keys = rgb_keys.ravel()
    unique_keys, inverse, counts = np.unique(
        flat_keys, return_inverse=True, return_counts=True
    )
    return ProvinceKeyIndex(
        unique_keys=unique_keys,
        inverse=inverse,
        counts=counts,
        shape=rgb_keys.shape,
    )


def render_palette_rgb_indexed(
    index: ProvinceKeyIndex,
    label_by_key: dict[int, str],
    palette: dict[str, tuple[int, int, int]],
) -> tuple[np.ndarray, int, int]:
    """Paint each province by label lookup; unmapped provinces and unknown labels -> white."""
    white = np.array(UNCOLORED_RGB, dtype=np.uint8)
    color_table = np.tile(white, (len(index.unique_keys), 1))
    painted = 0

    for idx, key in enumerate(index.unique_keys):
        label = label_by_key.get(int(key))
        if label is None:
            continue
        color = palette.get(label)
        if color is None:
            continue
        color_table[idx] = color
        painted += int(index.counts[idx])

    output = color_table[index.inverse].reshape(*index.shape, 3)
    return output, painted, index.total_pixels


def render_palette_rgb(
    model: ProvinceModel,
    label_by_key: dict[int, str],
    palette: dict[str, tuple[int, int, int]],
) -> tuple[np.ndarray, int, int]:
    """Paint each province by label lookup; unmapped provinces and unknown labels -> white."""
    index = model.key_index or province_key_index(model.rgb_keys)
    return render_palette_rgb_indexed(index, label_by_key, palette)


def count_labeled_pixels(
    rgb_keys: np.ndarray,
    label_by_key: dict[int, str],
) -> int:
    """Count pixels whose province key has a label, without building a full RGB array."""
    flat_keys = rgb_keys.ravel()
    unique_keys, counts = np.unique(flat_keys, return_counts=True)
    painted = 0
    for key, count in zip(unique_keys, counts):
        if int(key) in label_by_key:
            painted += int(count)
    return painted


def encode_png_rgb(array: np.ndarray, *, optimize: bool = True) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array, mode="RGB").save(buffer, format="PNG", optimize=optimize)
    return buffer.getvalue()


def render_palette_png_bytes(
    model: ProvinceModel,
    label_by_key: dict[int, str],
    palette: dict[str, tuple[int, int, int]],
    *,
    optimize: bool = True,
) -> tuple[bytes, int, int]:
    array, painted, total = render_palette_rgb(model, label_by_key, palette)
    return encode_png_rgb(array, optimize=optimize), painted, total


def render_palette_png_bytes_indexed(
    index: ProvinceKeyIndex,
    label_by_key: dict[int, str],
    palette: dict[str, tuple[int, int, int]],
    *,
    optimize: bool = True,
) -> tuple[bytes, int, int]:
    array, painted, total = render_palette_rgb_indexed(index, label_by_key, palette)
    return encode_png_rgb(array, optimize=optimize), painted, total


def render_direct_rgb(
    model: ProvinceModel,
    rgb_by_key: dict[int, tuple[int, int, int]],
) -> tuple[np.ndarray, int, int]:
    """Paint each province with an explicit RGB; unmapped provinces stay white."""
    index = model.key_index or province_key_index(model.rgb_keys)
    white = np.array(UNCOLORED_RGB, dtype=np.uint8)
    color_table = np.tile(white, (len(index.unique_keys), 1))
    painted = 0

    for idx, key in enumerate(index.unique_keys):
        color = rgb_by_key.get(int(key))
        if color is None:
            continue
        color_table[idx] = color
        painted += int(index.counts[idx])

    output = color_table[index.inverse].reshape(*index.shape, 3)
    return output, painted, index.total_pixels


def render_direct_rgb_png_bytes(
    model: ProvinceModel,
    rgb_by_key: dict[int, tuple[int, int, int]],
) -> tuple[bytes, int, int]:
    array, painted, total = render_direct_rgb(model, rgb_by_key)
    return encode_png_rgb(array), painted, total


def render_palette_layer(
    model: ProvinceModel,
    label_by_key: dict[int, str],
    palette: dict[str, tuple[int, int, int]],
    output_path: Path,
) -> tuple[int, int]:
    array, painted, total = render_palette_rgb(model, label_by_key, palette)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(array, mode="RGB").save(output_path, optimize=True)
    return painted, total
