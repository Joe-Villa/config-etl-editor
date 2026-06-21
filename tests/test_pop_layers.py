"""Tests for dynamic population map layers."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from interactive_map.edit.pops import add_pop, delete_pop  # noqa: E402
from interactive_map.map_session import MapSession  # noqa: E402
from interactive_map.pop_layers import (  # noqa: E402
    build_pop_total_json,
    build_slavery_json,
    compute_population_by_scope,
    compute_slavery_by_scope,
    pop_total_to_rgb,
    slavery_pop_to_rgb,
)
from interactive_map.foreign_investment import scope_key  # noqa: E402
from test_db_fixture import ensure_test_map_db  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"
TAG = "SIC"
STATE = "STATE_ABRUZZO"


class PopLayersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_test_map_db()

    def setUp(self) -> None:
        self.conn = sqlite3.connect(DB)
        self.added_ids: list[int] = []

    def tearDown(self) -> None:
        for pop_id in reversed(self.added_ids):
            delete_pop(self.conn, tag=TAG, state=STATE, pop_id=pop_id)
            self.conn.commit()
        self.conn.close()

    def test_pop_total_rgb_darkens_with_population(self) -> None:
        low = pop_total_to_rgb(1000, 1000000)
        high = pop_total_to_rgb(1000000, 1000000)
        self.assertLess(sum(high), sum(low))

    def test_slavery_rgb_darkens_with_slave_population(self) -> None:
        low = slavery_pop_to_rgb(1, 10000)
        high = slavery_pop_to_rgb(10000, 10000)
        self.assertLess(sum(high), sum(low))
        self.assertNotEqual(slavery_pop_to_rgb(0, 10000), low)

    def test_slavery_layer_detects_slave_pop(self) -> None:
        result = add_pop(
            self.conn,
            tag=TAG,
            state=STATE,
            culture="south_italian",
            religion="catholic",
            is_slaves=True,
            size=500,
        )
        self.conn.commit()
        self.added_ids.append(int(result["pop_id"]))
        slavery = compute_slavery_by_scope(self.conn)
        key = (TAG, STATE)
        self.assertTrue(slavery[key]["has_slaves"])
        self.assertGreaterEqual(int(slavery[key]["slave_pop"]), 500)

    def test_population_is_absolute_total_not_density(self) -> None:
        populations = compute_population_by_scope(self.conn)
        key = (TAG, STATE)
        self.assertGreater(populations.get(key, 0), 0)
        doc = build_pop_total_json(self.conn)
        self.assertEqual(doc["by_scope"][scope_key(TAG, STATE)], populations[key])

    def test_map_session_renders_pop_layers(self) -> None:
        session = MapSession.open(DB)
        try:
            self.assertGreater(len(session.layer_png("slavery")), 1000)
            self.assertGreater(len(session.layer_png("pop_total")), 1000)
            slavery_doc = session.json_document("slavery")
            pop_doc = session.json_document("pop_total")
            self.assertIn("by_scope", slavery_doc)
            self.assertIn("max_slave_pop", slavery_doc)
            self.assertIn("max_population", pop_doc)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
