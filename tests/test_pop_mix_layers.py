"""Tests for culture/religion population mix map layers."""

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
from interactive_map.foreign_investment import scope_key  # noqa: E402
from interactive_map.map_session import MapSession  # noqa: E402
from interactive_map.pop_layers import (  # noqa: E402
    build_pop_culture_json,
    build_pop_religion_json,
    compute_pop_mix_by_scope,
    mix_weighted_rgb,
)
from test_db_fixture import ensure_test_map_db  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"
TAG = "SIC"
STATE = "STATE_ABRUZZO"


class PopMixLayersTest(unittest.TestCase):
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

    def test_mix_weighted_rgb(self) -> None:
        mixed = mix_weighted_rgb([((200, 0, 0), 1), ((0, 0, 200), 1)])
        self.assertEqual(mixed, (100, 0, 100))

    def test_pop_culture_mix_uses_culture_colors(self) -> None:
        result = add_pop(
            self.conn,
            tag=TAG,
            state=STATE,
            culture="south_italian",
            religion="catholic",
            is_slaves=False,
            size=1000,
        )
        self.conn.commit()
        self.added_ids.append(int(result["pop_id"]))
        mix = compute_pop_mix_by_scope(self.conn, dimension="culture")
        key = (TAG, STATE)
        self.assertIn(key, mix)
        doc = build_pop_culture_json(self.conn)
        scope = doc["by_scope"][scope_key(TAG, STATE)]
        self.assertGreater(scope["total"], 0)
        self.assertTrue(scope["breakdown"])

    def test_pop_religion_resolves_null_religion_to_culture_default(self) -> None:
        row = self.conn.execute(
            """
            SELECT tag, state
            FROM st_pop
            WHERE religion IS NULL
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            self.skipTest("数据库中没有 religion 为空的人口条目")
        tag, state = str(row[0]), str(row[1])
        doc = build_pop_religion_json(self.conn)
        scope = doc["by_scope"].get(scope_key(tag, state))
        self.assertIsNotNone(scope)
        religions = {item["religion"] for item in scope["breakdown"]}
        self.assertTrue(religions)

    def test_map_session_renders_pop_mix_layers(self) -> None:
        session = MapSession.open(DB)
        try:
            self.assertGreater(len(session.layer_png("pop_culture")), 1000)
            self.assertGreater(len(session.layer_png("pop_religion")), 1000)
            culture_doc = session.json_document("pop_culture")
            religion_doc = session.json_document("pop_religion")
            self.assertEqual(culture_doc["dimension"], "culture")
            self.assertEqual(religion_doc["dimension"], "religion")
            self.assertIn("by_scope", culture_doc)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
