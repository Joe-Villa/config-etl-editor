"""Tests for foreign investment dynamic layer."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.buildings import add_building, delete_building  # noqa: E402
from interactive_map.foreign_investment import (  # noqa: E402
    build_foreign_investment_json,
    compute_foreign_by_scope,
    level_to_rgb,
    scope_key,
)
from interactive_map.map_session import MapSession  # noqa: E402
from interactive_map.palette import UNCOLORED_RGB  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"
TAG = "SIC"
STATE = "STATE_ABRUZZO"
FOREIGN_TAG = "AUS"
BUILDING = "building_furniture_manufactory"


class ForeignInvestmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "map_db"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def setUp(self) -> None:
        self.conn = sqlite3.connect(DB)
        self.added_ids: list[int] = []

    def tearDown(self) -> None:
        for bld_id in reversed(self.added_ids):
            delete_building(self.conn, tag=TAG, state=STATE, bld_id=bld_id)
        self.conn.commit()
        self.conn.close()

    def test_level_one_is_visibly_colored(self) -> None:
        self.assertNotEqual(level_to_rgb(1, 10), UNCOLORED_RGB)
        self.assertNotEqual(level_to_rgb(1, 1), UNCOLORED_RGB)

    def test_higher_levels_are_darker(self) -> None:
        low = level_to_rgb(1, 20)
        high = level_to_rgb(20, 20)
        self.assertLess(sum(high), sum(low))

    def test_foreign_building_increases_scope_total(self) -> None:
        before = compute_foreign_by_scope(self.conn).get((TAG, STATE), 0)
        result = add_building(
            self.conn,
            tag=TAG,
            state=STATE,
            building=BUILDING,
            pms=None,
            level=3,
            ownership_type="country",
            owner_tag=FOREIGN_TAG,
        )
        bld_id = int(result["bld_id"])
        self.added_ids.append(bld_id)
        self.conn.commit()
        after = compute_foreign_by_scope(self.conn)[(TAG, STATE)]
        self.assertEqual(after, before + 3)

    def test_domestic_building_does_not_count(self) -> None:
        result = add_building(
            self.conn,
            tag=TAG,
            state=STATE,
            building=BUILDING,
            pms=None,
            level=5,
            ownership_type="country",
            owner_tag=TAG,
        )
        bld_id = int(result["bld_id"])
        self.added_ids.append(bld_id)
        self.conn.commit()
        key = scope_key(TAG, STATE)
        payload = build_foreign_investment_json(self.conn)
        self.assertNotIn(key, payload["by_scope"])

    def test_map_session_renders_foreign_layer(self) -> None:
        session = MapSession.open(DB)
        try:
            png = session.layer_png("foreign_investment")
            self.assertGreater(len(png), 1000)
            doc = session.json_document("foreign_investment")
            self.assertIn("by_scope", doc)
            self.assertIn("max_level", doc)
        finally:
            session.close()

    def test_refresh_rebuilds_foreign_layer(self) -> None:
        session = MapSession.open(DB)
        try:
            first = session.layer_png("foreign_investment")
            result = add_building(
                session.conn,
                tag=TAG,
                state=STATE,
                building=BUILDING,
                pms=None,
                level=2,
                ownership_type="country",
                owner_tag=FOREIGN_TAG,
            )
            bld_id = int(result["bld_id"])
            self.added_ids.append(bld_id)
            session.conn.commit()
            session.refresh()
            second = session.layer_png("foreign_investment")
            self.assertIsNot(first, second)
            key = scope_key(TAG, STATE)
            self.assertGreaterEqual(
                session.json_document("foreign_investment")["by_scope"].get(key, 0),
                2,
            )
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
