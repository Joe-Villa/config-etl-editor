"""Incremental repaint for territory edits: patch affected provinces only."""

from __future__ import annotations

import base64
import sqlite3
from collections import defaultdict
from typing import Any

import numpy as np

from interactive_map.borders import (
    COUNTRY_BORDER_RGBA,
    encode_rgba_png,
    render_border_country_rgba,
)
from interactive_map.compositor import encode_png_rgb, render_palette_rgb
from interactive_map.country_type_layer import build_country_type_labels
from interactive_map.db_reader import (
    load_provinces_for_tag,
    load_provinces_in_geographic_state,
    load_provinces_in_scope,
    load_tag_country_types,
    load_tag_state_types,
)
from interactive_map.palette import COUNTRY_TYPE_PALETTE, INCORPORATION_PALETTE, UNCOLORED_RGB
from interactive_map.png_util import province_hex_to_key
from interactive_map.province_model import ProvinceModel

TERRITORY_PATCH_LAYERS = (
    "ownership",
    "incorporation",
    "country_type",
    "border_country",
)

TERRITORY_MAIN_VIEW_LAYERS = (
    "ownership",
    "incorporation",
    "country_type",
)

DATA_DRIVEN_VIEW_LAYERS = (
    "homeland",
    "claims",
    "foreign_investment",
    "building_level",
    "slavery",
    "pop_total",
    "pop_culture",
    "pop_religion",
)

STATIC_VIEW_LAYERS = (
    "terrain",
    "hubs",
    "strategic_region",
    "raw",
)

DYNAMIC_VIEW_LAYERS = TERRITORY_MAIN_VIEW_LAYERS + DATA_DRIVEN_VIEW_LAYERS


def view_layer_types() -> dict[str, str]:
    """Map each main view layer id to ``static`` or ``dynamic``."""
    types = {name: "static" for name in STATIC_VIEW_LAYERS}
    for name in DYNAMIC_VIEW_LAYERS:
        types[name] = "dynamic"
    return types


def build_province_pixel_indices(rgb_keys: np.ndarray) -> dict[int, np.ndarray]:
    """Map each province key to flat pixel indices in ``rgb_keys.ravel()``."""
    flat = rgb_keys.ravel()
    order = np.argsort(flat, kind="mergesort")
    sorted_flat = flat[order]
    unique, split = np.unique(sorted_flat, return_index=True)
    split_points = list(split) + [len(order)]
    return {
        int(key): order[split_points[i] : split_points[i + 1]]
        for i, key in enumerate(unique)
    }


def build_province_neighbors(rgb_keys: np.ndarray) -> dict[int, set[int]]:
    """Province keys that share a raster edge (4-neighborhood)."""
    neighbors: dict[int, set[int]] = defaultdict(set)

    left = rgb_keys[:, :-1]
    right = rgb_keys[:, 1:]
    ys, xs = np.nonzero(left != right)
    for y, x in zip(ys, xs):
        key_a = int(rgb_keys[y, x])
        key_b = int(rgb_keys[y, x + 1])
        neighbors[key_a].add(key_b)
        neighbors[key_b].add(key_a)

    top = rgb_keys[:-1, :]
    bottom = rgb_keys[1:, :]
    ys, xs = np.nonzero(top != bottom)
    for y, x in zip(ys, xs):
        key_a = int(rgb_keys[y, x])
        key_b = int(rgb_keys[y + 1, x])
        neighbors[key_a].add(key_b)
        neighbors[key_b].add(key_a)

    return dict(neighbors)


def build_country_border_segments(
    rgb_keys: np.ndarray,
) -> list[tuple[int, int, int, int]]:
    """Border pixel coords with the two adjacent province keys (y, x, key_a, key_b).

    Each raster edge emits two segment rows (one per pixel) so incremental patches
    match full renders that mark both sides of an adjacency.
    """
    segments: list[tuple[int, int, int, int]] = []

    left = rgb_keys[:, :-1]
    right = rgb_keys[:, 1:]
    ys, xs = np.nonzero(left != right)
    for y, x in zip(ys, xs):
        key_a = int(rgb_keys[y, x])
        key_b = int(rgb_keys[y, x + 1])
        segments.append((int(y), int(x), key_a, key_b))
        segments.append((int(y), int(x + 1), key_a, key_b))

    top = rgb_keys[:-1, :]
    bottom = rgb_keys[1:, :]
    ys, xs = np.nonzero(top != bottom)
    for y, x in zip(ys, xs):
        key_a = int(rgb_keys[y, x])
        key_b = int(rgb_keys[y + 1, x])
        segments.append((int(y), int(x), key_a, key_b))
        segments.append((int(y + 1), int(x), key_a, key_b))

    return segments


def expand_with_neighbors(
    neighbors: dict[int, set[int]],
    keys: set[int],
) -> set[int]:
    expanded = set(keys)
    for key in keys:
        expanded.update(neighbors.get(key, ()))
    return expanded


def paint_provinces_rgb(
    rgb: np.ndarray,
    indices: dict[int, np.ndarray],
    keys: set[int],
    label_by_key: dict[int, str],
    palette: dict[str, tuple[int, int, int]],
    *,
    default: tuple[int, int, int] = UNCOLORED_RGB,
) -> None:
    flat_rgb = rgb.reshape(-1, 3)
    white = np.array(default, dtype=np.uint8)
    for key in keys:
        pixel_indices = indices.get(key)
        if pixel_indices is None:
            continue
        label = label_by_key.get(key)
        if label is None:
            flat_rgb[pixel_indices] = white
            continue
        color = palette.get(label)
        if color is None:
            flat_rgb[pixel_indices] = white
        else:
            flat_rgb[pixel_indices] = color


def patch_country_border_rgba(
    rgba: np.ndarray,
    segments: list[tuple[int, int, int, int]],
    province_tag_state: dict[int, tuple[str, str]],
    dirty_keys: set[int],
    *,
    color_on: tuple[int, int, int, int] = COUNTRY_BORDER_RGBA,
) -> None:
    transparent = (0, 0, 0, 0)
    for y, x, key_a, key_b in segments:
        if key_a not in dirty_keys and key_b not in dirty_keys:
            continue
        tag_a = province_tag_state.get(key_a, (None,))[0]
        tag_b = province_tag_state.get(key_b, (None,))[0]
        # Match full render: border when labels differ (incl. land vs unowned sea).
        if tag_a == tag_b:
            rgba[y, x] = transparent
        else:
            rgba[y, x] = color_on


def collect_dirty_province_keys(
    conn: sqlite3.Connection,
    result: dict[str, Any],
) -> set[int]:
    """Derive province keys whose ownership/incorporation colors may have changed."""
    keys: set[int] = set()

    if province_db := result.get("province_db"):
        keys.add(province_hex_to_key(str(province_db)))

    op = str(result.get("op", ""))
    tag = result.get("tag") or result.get("to_tag")
    state = result.get("state")

    if op == "change_state_type" and tag and state:
        keys.update(load_provinces_in_scope(conn, str(tag), str(state)))
    elif op == "incorporate_all_states" and tag:
        for scope_state in result.get("states_updated", []):
            keys.update(load_provinces_in_scope(conn, str(tag), str(scope_state)))
    elif op == "change_tag":
        new_tag = result.get("to_tag") or result.get("tag")
        if new_tag:
            keys.update(load_provinces_for_tag(conn, str(new_tag)))
    elif op.startswith("release_country"):
        for geo_state in result.get("states_released", []):
            keys.update(load_provinces_in_geographic_state(conn, str(geo_state)))
    elif op.startswith("acquire_all_homelands"):
        for geo_state in result.get("states_acquired", []):
            keys.update(load_provinces_in_geographic_state(conn, str(geo_state)))
    elif result.get("states_expanded"):
        for geo_state in result["states_expanded"]:
            keys.update(load_provinces_in_geographic_state(conn, str(geo_state)))
    elif state and (
        result.get("from_tag")
        or result.get("from_tags")
        or "provinces_moved" in result
        or op.startswith("expand_to_full_state")
    ):
        keys.update(load_provinces_in_geographic_state(conn, str(state)))
    elif result.get("states_transferred"):
        victim = result.get("from_tag") or result.get("victim_tag")
        acquirer = result.get("to_tag") or result.get("tag")
        if victim:
            keys.update(load_provinces_for_tag(conn, str(victim)))
        if acquirer:
            keys.update(load_provinces_for_tag(conn, str(acquirer)))
        for geo_state in result.get("states_moved", []):
            keys.update(load_provinces_in_geographic_state(conn, str(geo_state)))

    for nested in result.get("transfers", []) + result.get("expansions", []):
        if isinstance(nested, dict):
            keys.update(collect_dirty_province_keys(conn, nested))

    return keys


def edit_touches_foreign_investment(result: dict[str, Any]) -> bool:
    if int(result.get("foreign_ownership_updates") or 0) > 0:
        return True
    cascade = result.get("cascade")
    if isinstance(cascade, dict):
        annex = cascade.get("annexation")
        if isinstance(annex, dict) and int(annex.get("foreign_ownership_updates") or 0) > 0:
            return True
    for nested in result.get("transfers", []) + result.get("expansions", []):
        if isinstance(nested, dict) and edit_touches_foreign_investment(nested):
            return True
    return (
        bool(result.get("annexed_source_tag"))
        or bool(result.get("annexed_tags"))
        or bool(result.get("annexed_releaser"))
    )


def patch_scenario_for_provinces(
    conn: sqlite3.Connection,
    model: ProvinceModel,
    province_tag_state: dict[int, tuple[str, str]],
    prov_keys: set[int],
    *,
    tag_state_types: dict[tuple[str, str], str] | None = None,
) -> None:
    """Reload ``st_prov`` rows for ``prov_keys`` and update in-memory scenario labels."""
    if not prov_keys:
        return

    if tag_state_types is None:
        tag_state_types = load_tag_state_types(conn)

    tag_country_types = load_tag_country_types(conn)

    hex_keys = []
    key_by_hex: dict[str, int] = {}
    for key in prov_keys:
        hex_db = f"x{(key >> 16) & 0xFF:02X}{(key >> 8) & 0xFF:02X}{key & 0xFF:02X}"
        hex_keys.append(hex_db)
        key_by_hex[hex_db] = key

    placeholders = ",".join("?" for _ in hex_keys)
    rows = conn.execute(
        f"SELECT tag, state, province FROM st_prov WHERE province IN ({placeholders})",
        hex_keys,
    ).fetchall()
    seen: set[int] = set()

    for tag, scope_state, province in rows:
        key = key_by_hex.get(str(province)) or province_hex_to_key(str(province))
        seen.add(key)
        province_tag_state[key] = (str(tag), str(scope_state))
        model.province_tag_state[key] = (str(tag), str(scope_state))
        model.ownership_tag[key] = str(tag)
        state_type = tag_state_types.get((str(tag), str(scope_state)), "incorporated")
        model.incorporation[key] = (
            "unincorporated" if state_type == "unincorporated" else "incorporated"
        )
        model.country_type[key] = tag_country_types.get(str(tag), "recognized")

    for key in prov_keys - seen:
        province_tag_state.pop(key, None)
        model.province_tag_state.pop(key, None)
        model.ownership_tag.pop(key, None)
        model.incorporation.pop(key, None)
        model.country_type.pop(key, None)


def patch_incorporation_for_scopes(
    conn: sqlite3.Connection,
    model: ProvinceModel,
    tag: str,
    states: list[str],
    *,
    tag_state_types: dict[tuple[str, str], str] | None = None,
) -> set[int]:
    """Update incorporation labels for scope states without reloading ownership."""
    if tag_state_types is None:
        tag_state_types = load_tag_state_types(conn)
    keys: set[int] = set()
    for scope_state in states:
        state_type = tag_state_types.get((tag, scope_state), "incorporated")
        label = "unincorporated" if state_type == "unincorporated" else "incorporated"
        for key in load_provinces_in_scope(conn, tag, scope_state):
            keys.add(key)
            model.incorporation[key] = label
    return keys


def build_territory_layer_array(
    layer: str,
    model: ProvinceModel,
    province_tag_state: dict[int, tuple[str, str]],
    ownership_palette: dict[str, tuple[int, int, int]],
    tag_country_types: dict[str, str],
) -> np.ndarray:
    """Build one territory raster layer from the in-memory scenario model."""
    if layer == "ownership":
        rgb, _, _ = render_palette_rgb(model, model.ownership_tag, ownership_palette)
        return rgb
    if layer == "incorporation":
        rgb, _, _ = render_palette_rgb(model, model.incorporation, INCORPORATION_PALETTE)
        return rgb
    if layer == "country_type":
        rgb, _, _ = render_palette_rgb(
            model,
            build_country_type_labels(model, tag_country_types),
            COUNTRY_TYPE_PALETTE,
        )
        return rgb
    if layer == "border_country":
        return render_border_country_rgba(model.rgb_keys, province_tag_state)
    raise KeyError(layer)


def build_territory_layer_arrays(
    model: ProvinceModel,
    province_tag_state: dict[int, tuple[str, str]],
    ownership_palette: dict[str, tuple[int, int, int]],
    tag_country_types: dict[str, str],
) -> dict[str, np.ndarray]:
    return {
        layer: build_territory_layer_array(
            layer,
            model,
            province_tag_state,
            ownership_palette,
            tag_country_types,
        )
        for layer in TERRITORY_PATCH_LAYERS
    }


def encode_territory_layer_pngs(arrays: dict[str, np.ndarray]) -> dict[str, bytes]:
    return {
        "ownership": encode_png_rgb(arrays["ownership"]),
        "incorporation": encode_png_rgb(arrays["incorporation"]),
        "country_type": encode_png_rgb(arrays["country_type"]),
        "border_country": encode_rgba_png(arrays["border_country"]),
    }


def compute_dirty_bbox(
    dirty_paint: set[int],
    province_indices: dict[int, np.ndarray],
    border_segments: list[tuple[int, int, int, int]],
    dirty_border: set[int],
    *,
    width: int,
    height: int,
    padding: int = 1,
) -> tuple[int, int, int, int] | None:
    """Return ``(x, y, w, h)`` bounding box for incremental layer patches."""
    ys: list[int] = []
    xs: list[int] = []
    for key in dirty_paint:
        pixel_indices = province_indices.get(key)
        if pixel_indices is None or len(pixel_indices) == 0:
            continue
        flat = np.asarray(pixel_indices, dtype=np.int64)
        ys.extend((flat // width).tolist())
        xs.extend((flat % width).tolist())
    for y, x, key_a, key_b in border_segments:
        if key_a in dirty_border or key_b in dirty_border:
            ys.append(int(y))
            xs.append(int(x))
    if not ys:
        return None
    x0 = max(0, min(xs) - padding)
    y0 = max(0, min(ys) - padding)
    x1 = min(width, max(xs) + padding + 1)
    y1 = min(height, max(ys) + padding + 1)
    return x0, y0, x1 - x0, y1 - y0


def encode_territory_layer_patches(
    arrays: dict[str, np.ndarray],
    bbox: tuple[int, int, int, int],
    *,
    layers: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """Encode cropped PNG patches for selected territory layers inside ``bbox``."""
    target = layers or TERRITORY_PATCH_LAYERS
    x, y, w, h = bbox
    patches: dict[str, dict[str, Any]] = {}
    for layer in target:
        if layer not in arrays:
            continue
        crop = arrays[layer][y : y + h, x : x + w]
        if layer == "border_country":
            png = encode_rgba_png(crop)
        else:
            png = encode_png_rgb(crop, optimize=False)
        patches[layer] = {"x": x, "y": y, "w": w, "h": h, "png": png}
    return patches


def territory_patches_for_view(patches: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """JSON-safe patch payload (base64 PNG) for ``view_patch.layer_patches``."""
    return {
        layer: {
            "x": int(meta["x"]),
            "y": int(meta["y"]),
            "w": int(meta["w"]),
            "h": int(meta["h"]),
            "png_b64": base64.standard_b64encode(meta["png"]).decode("ascii"),
        }
        for layer, meta in patches.items()
    }
