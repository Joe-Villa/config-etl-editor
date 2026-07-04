"""Tests for population edit operations."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.pops import (  # noqa: E402
    POP_SIZE_ERROR,
    add_pop,
    delete_pop,
    load_pop_options,
    parse_pop_size,
    update_pop,
)

DB = ROOT / "output" / "test_map_editor.sqlite"
TAG = "SIC"
STATE = "STATE_ABRUZZO"
CULTURE = "south_italian"


class EditPopsTest(unittest.TestCase):
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
        for pop_id in reversed(self.added_ids):
            self.conn.execute("DELETE FROM st_pop WHERE id = ?", (pop_id,))
        self.conn.commit()
        self.conn.close()

    def test_load_pop_options(self) -> None:
        opts = load_pop_options(self.conn, TAG, STATE)
        self.assertEqual(opts["tag"], TAG)
        self.assertIn(CULTURE, opts["cultures"])
        self.assertGreater(len(opts["religions"]), 0)
        self.assertFalse(opts["defaults"]["is_slaves"])

    def test_parse_pop_size_rejects_invalid(self) -> None:
        for raw in (0, -1, 2.5, "1.5", "x"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError) as ctx:
                    parse_pop_size(raw)
                self.assertEqual(str(ctx.exception), POP_SIZE_ERROR)

    def test_add_update_delete_pop(self) -> None:
        result = add_pop(
            self.conn,
            tag=TAG,
            state=STATE,
            culture=CULTURE,
            religion="catholic",
            is_slaves=False,
            size=1234,
        )
        self.conn.commit()
        pop_id = int(result["pop_id"])
        self.added_ids.append(pop_id)
        row = self.conn.execute(
            "SELECT culture, religion, is_slaves, size FROM st_pop WHERE id = ?",
            (pop_id,),
        ).fetchone()
        self.assertEqual(row[0], CULTURE)
        self.assertEqual(row[1], "catholic")
        self.assertEqual(int(row[2]), 0)
        self.assertEqual(int(row[3]), 1234)

        update_pop(
            self.conn,
            tag=TAG,
            state=STATE,
            pop_id=pop_id,
            culture=CULTURE,
            religion="",
            is_slaves=True,
            size=2000,
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT religion, is_slaves, size FROM st_pop WHERE id = ?",
            (pop_id,),
        ).fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(int(row[1]), 1)
        self.assertEqual(int(row[2]), 2000)

        delete_pop(self.conn, tag=TAG, state=STATE, pop_id=pop_id)
        self.conn.commit()
        self.added_ids.remove(pop_id)
        gone = self.conn.execute(
            "SELECT 1 FROM st_pop WHERE id = ?", (pop_id,)
        ).fetchone()
        self.assertIsNone(gone)

    def test_add_pop_rejects_invalid_size(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            add_pop(
                self.conn,
                tag=TAG,
                state=STATE,
                culture=CULTURE,
                size=0,
            )
        self.assertEqual(str(ctx.exception), POP_SIZE_ERROR)


if __name__ == "__main__":
    unittest.main()
