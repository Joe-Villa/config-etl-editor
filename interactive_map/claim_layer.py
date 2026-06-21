"""Geographic-state claim layer: darkness scales with absolute claim-tag count."""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from interactive_map.compositor import render_palette_png_bytes
from interactive_map.db_reader import load_province_geographic_state
from interactive_map.palette import (
    CLAIM_COUNT_SCALE,
    CLAIM_MAX_RGB,
    CLAIM_MIN_RGB,
    UNCOLORED_RGB,
)
from interactive_map.province_model import ProvinceModel


def claim_count_to_rgb(count: int) -> tuple[int, int, int]:
    """Map claim count to RGB using a fixed absolute scale (not relative to map max)."""
    if count <= 0:
        return UNCOLORED_RGB
    if CLAIM_COUNT_SCALE <= 1:
        return CLAIM_MAX_RGB
    t = min((count - 1) / (CLAIM_COUNT_SCALE - 1), 1.0)
    return tuple(
        int(CLAIM_MIN_RGB[i] + t * (CLAIM_MAX_RGB[i] - CLAIM_MIN_RGB[i]))
        for i in range(3)
    )


def load_state_claims(conn: sqlite3.Connection) -> tuple[dict[str, list[str]], dict[str, int]]:
    tags_by_state: dict[str, list[str]] = defaultdict(list)
    for state, claim_tag in conn.execute(
        "SELECT state, claim_tag FROM geo_claim ORDER BY state, claim_tag"
    ):
        tags_by_state[str(state)].append(str(claim_tag))
    counts = {state: len(tags) for state, tags in tags_by_state.items()}
    return dict(tags_by_state), counts


def build_claim_palette(claim_counts: set[int]) -> dict[str, tuple[int, int, int]]:
    palette: dict[str, tuple[int, int, int]] = {
        "sea": UNCOLORED_RGB,
        "0": UNCOLORED_RGB,
    }
    for count in sorted(claim_counts):
        if count > 0:
            palette[str(count)] = claim_count_to_rgb(count)
    return palette


def build_claim_labels(
    model: ProvinceModel,
    province_geographic_state: dict[int, str],
    state_claim_counts: dict[str, int],
) -> dict[int, str]:
    labels: dict[int, str] = {}
    for key, terrain in model.terrain.items():
        if terrain == "sea":
            labels[key] = "0"
            continue
        geo_state = province_geographic_state.get(key)
        if not geo_state:
            labels[key] = "0"
            continue
        labels[key] = str(state_claim_counts.get(geo_state, 0))
    return labels


def render_claims_png(
    model: ProvinceModel,
    conn: sqlite3.Connection,
    *,
    province_geographic_state: dict[int, str] | None = None,
) -> bytes:
    if province_geographic_state is None:
        province_geographic_state = load_province_geographic_state(conn)
    _, state_claim_counts = load_state_claims(conn)
    labels = build_claim_labels(model, province_geographic_state, state_claim_counts)
    palette = build_claim_palette({int(v) for v in labels.values() if v != "sea"})
    png_bytes, _, _ = render_palette_png_bytes(model, labels, palette)
    return png_bytes


def build_claims_json(conn: sqlite3.Connection) -> dict:
    state_claim_tags, state_claim_counts = load_state_claims(conn)
    all_geo_states = {str(row[0]) for row in conn.execute("SELECT state FROM geo_state")}
    claimed_states = set(state_claim_tags)
    legend_counts = list(range(0, CLAIM_COUNT_SCALE + 1))
    return {
        "state_claim_tags": state_claim_tags,
        "state_claim_counts": state_claim_counts,
        "scale_max": CLAIM_COUNT_SCALE,
        "legend": [
            {"count": count, "rgb": list(claim_count_to_rgb(count))}
            for count in legend_counts
        ],
        "stats": {
            "claimed_states": len(claimed_states),
            "unclaimed_states": len(all_geo_states - claimed_states),
            "max_claim_count": max(state_claim_counts.values(), default=0),
        },
    }
