"""Tests for geographic-state claim view layer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.claim_layer import (  # noqa: E402
    CLAIM_COUNT_SCALE,
    build_claim_labels,
    claim_count_to_rgb,
    load_state_claims,
)
from interactive_map.palette import UNCOLORED_RGB


def _claim_layer_conn():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE geo_state (state TEXT PRIMARY KEY);
        CREATE TABLE geo_claim (
            state TEXT NOT NULL,
            claim_tag TEXT NOT NULL,
            PRIMARY KEY (state, claim_tag)
        );
        """
    )
    conn.executemany(
        "INSERT INTO geo_state (state) VALUES (?)",
        [("STATE_A",), ("STATE_B",), ("STATE_C",)],
    )
    conn.executemany(
        "INSERT INTO geo_claim (state, claim_tag) VALUES (?, ?)",
        [
            ("STATE_A", "FRA"),
            ("STATE_A", "GBR"),
            ("STATE_B", "FRA"),
        ],
    )
    return conn


class ClaimLayerTest(unittest.TestCase):
    def test_claim_count_to_rgb_is_absolute_not_relative(self) -> None:
        rgb_one = claim_count_to_rgb(1)
        rgb_one_again = claim_count_to_rgb(1)
        self.assertEqual(rgb_one, rgb_one_again)
        self.assertNotEqual(rgb_one, UNCOLORED_RGB)
        self.assertEqual(claim_count_to_rgb(0), UNCOLORED_RGB)
        self.assertEqual(claim_count_to_rgb(CLAIM_COUNT_SCALE), claim_count_to_rgb(99))

    def test_load_state_claims(self) -> None:
        conn = _claim_layer_conn()
        tags, counts = load_state_claims(conn)
        self.assertEqual(counts["STATE_A"], 2)
        self.assertEqual(counts["STATE_B"], 1)
        self.assertNotIn("STATE_C", counts)
        self.assertEqual(tags["STATE_A"], ["FRA", "GBR"])

    def test_build_claim_labels_use_geo_state(self) -> None:
        from types import SimpleNamespace

        model = SimpleNamespace(
            terrain={
                1: "sea",
                2: "normal",
                3: "normal",
                4: "normal",
            }
        )
        province_geographic_state = {2: "STATE_A", 3: "STATE_B", 4: "STATE_C"}
        state_claim_counts = {"STATE_A": 2, "STATE_B": 1}
        labels = build_claim_labels(model, province_geographic_state, state_claim_counts)
        self.assertEqual(labels[1], "0")
        self.assertEqual(labels[2], "2")
        self.assertEqual(labels[3], "1")
        self.assertEqual(labels[4], "0")


if __name__ == "__main__":
    unittest.main()
