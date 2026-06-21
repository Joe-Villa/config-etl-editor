"""Generate province / state / country border overlays."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from interactive_map.compositor import ProvinceKeyIndex, province_key_index
from interactive_map.png_util import province_rgb_keys_from_bytes

COUNTRY_BORDER_RGBA = (255, 215, 0, 240)


def _adjacency_border(mask: np.ndarray) -> np.ndarray:
    border = np.zeros(mask.shape, dtype=bool)
    border[:, 1:] |= mask[:, 1:] != mask[:, :-1]
    border[:, :-1] |= mask[:, 1:] != mask[:, :-1]
    border[1:, :] |= mask[1:, :] != mask[:-1, :]
    border[:-1, :] |= mask[1:, :] != mask[:-1, :]
    return border


def _border_mask_from_key_index(
    index: ProvinceKeyIndex,
    province_labels: dict[int, str],
) -> np.ndarray:
    label_index: dict[str, int] = {}
    ids = np.full(len(index.unique_keys), -1, dtype=np.int32)
    for idx, key in enumerate(index.unique_keys):
        label = province_labels.get(int(key))
        if label is None:
            continue
        lid = label_index.setdefault(label, len(label_index))
        ids[idx] = lid
    grid = ids[index.inverse].reshape(index.shape)
    return _adjacency_border(grid)


def _border_mask_from_labels(
    rgb_keys: np.ndarray,
    province_labels: dict[int, str],
) -> np.ndarray:
    return _border_mask_from_key_index(province_key_index(rgb_keys), province_labels)


def _encode_rgba_png(
    mask: np.ndarray,
    color: tuple[int, int, int, int],
    *,
    optimize: bool = True,
) -> bytes:
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask] = color
    return encode_rgba_png(rgba, optimize=optimize)


def encode_rgba_png(rgba: np.ndarray, *, optimize: bool = True) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(
        buffer, format="PNG", optimize=optimize
    )
    return buffer.getvalue()


def render_border_country_rgba(
    rgb_keys: np.ndarray,
    province_tag_state: dict[int, tuple[str, str]],
    *,
    color: tuple[int, int, int, int] = COUNTRY_BORDER_RGBA,
) -> np.ndarray:
    province_tag = {key: tag for key, (tag, _state) in province_tag_state.items()}
    mask = _border_mask_from_labels(rgb_keys, province_tag)
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[mask] = color
    return rgba


def render_border_country_png(
    rgb_keys: np.ndarray,
    province_tag_state: dict[int, tuple[str, str]],
) -> bytes:
    return encode_rgba_png(
        render_border_country_rgba(rgb_keys, province_tag_state),
    )


def render_static_border_state_png(
    rgb_keys: np.ndarray,
    key_index: ProvinceKeyIndex,
    province_geographic_state: dict[int, str],
    *,
    optimize: bool = True,
) -> bytes:
    state_mask = _border_mask_from_key_index(key_index, province_geographic_state)
    return _encode_rgba_png(state_mask, (20, 20, 20, 220), optimize=optimize)


def render_static_border_province_png(
    rgb_keys: np.ndarray,
    *,
    optimize: bool = True,
) -> bytes:
    province_mask = _adjacency_border(rgb_keys)
    return _encode_rgba_png(province_mask, (255, 255, 255, 160), optimize=optimize)


def render_static_border_pngs(
    rgb_keys: np.ndarray,
    key_index: ProvinceKeyIndex,
    province_geographic_state: dict[int, str],
    *,
    optimize: bool = True,
) -> dict[str, bytes]:
    """Bake border_state + border_province from one shared province key index."""
    return {
        "border_province": render_static_border_province_png(
            rgb_keys, optimize=optimize
        ),
        "border_state": render_static_border_state_png(
            rgb_keys,
            key_index,
            province_geographic_state,
            optimize=optimize,
        ),
    }


def render_border_pngs(
    rgb_keys: np.ndarray,
    province_tag_state: dict[int, tuple[str, str]],
    province_geographic_state: dict[int, str],
) -> dict[str, bytes]:
    layers = render_static_border_pngs(
        rgb_keys,
        province_key_index(rgb_keys),
        province_geographic_state,
    )
    layers["border_country"] = render_border_country_png(rgb_keys, province_tag_state)
    return layers


def generate_border_layers(
    png_bytes: bytes,
    province_tag_state: dict[int, tuple[str, str]],
    province_geographic_state: dict[int, str],
    output_dir: Path,
) -> tuple[int, int, int]:
    rgb_keys, _ = province_rgb_keys_from_bytes(png_bytes)
    layers = render_border_pngs(rgb_keys, province_tag_state, province_geographic_state)

    def save(name: str, path: Path) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(layers[name])
        mask = np.array(Image.open(io.BytesIO(layers[name])).convert("RGBA"))[:, :, 3] > 0
        return int(mask.sum())

    prov_px = save("border_province", output_dir / "border_province.png")
    state_px = save("border_state", output_dir / "border_state.png")
    country_px = save("border_country", output_dir / "border_country.png")
    return prov_px, state_px, country_px
