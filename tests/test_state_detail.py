"""Tests for tag+state detail loader."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.state_detail import load_state_detail_json  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


class StateDetailTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "map_db"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def test_load_sic_abruzzo(self) -> None:
        import sqlite3

        conn = sqlite3.connect(DB)
        detail = load_state_detail_json(conn, "SIC", "STATE_ABRUZZO")
        conn.close()
        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail["tag"], "SIC")
        self.assertIn("south_italian", detail["homelands"])
        self.assertGreater(len(detail["provinces"]), 0)
        self.assertTrue(detail["provinces"][0].startswith("#"))
        self.assertIn("hubs", detail)
        self.assertIsInstance(detail["hubs"], list)
        for hub in detail["hubs"]:
            self.assertIn(hub["hub_type"], ("city", "port", "farm", "mine", "wood"))
            self.assertTrue(hub["province"].startswith("#"))
        self.assertGreater(len(detail["buildings"]), 0)
        self.assertGreater(len(detail["pops"]), 0)
        self.assertIn("id", detail["pops"][0])
        self.assertIn("ownerships", detail["buildings"][0])
        self.assertIn("pms", detail["buildings"][0])

    def test_missing_tag_state_returns_none(self) -> None:
        import sqlite3

        conn = sqlite3.connect(DB)
        detail = load_state_detail_json(conn, "ZZZ", "STATE_ABRUZZO")
        conn.close()
        self.assertIsNone(detail)


if __name__ == "__main__":
    unittest.main()
