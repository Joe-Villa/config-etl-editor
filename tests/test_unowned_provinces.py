"""Tests for partial vs total unowned land province handling."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_db import _check_unowned_land_provinces  # noqa: E402
from warn import ImportLog  # noqa: E402


def _minimal_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE ref_tag (tag TEXT PRIMARY KEY);
        CREATE TABLE ref_sr (
            state TEXT PRIMARY KEY,
            sr_id INTEGER NOT NULL,
            city TEXT, port TEXT, farm TEXT, mine TEXT, wood TEXT
        );
        CREATE TABLE ref_sr_prov (state TEXT NOT NULL, province TEXT NOT NULL, PRIMARY KEY (state, province));
        CREATE TABLE geo_state (state TEXT PRIMARY KEY);
        CREATE TABLE st (state TEXT NOT NULL, tag TEXT NOT NULL, state_type TEXT NOT NULL, PRIMARY KEY (state, tag));
        CREATE TABLE st_prov (
            province TEXT NOT NULL PRIMARY KEY,
            state TEXT NOT NULL,
            tag TEXT NOT NULL
        );
        """
    )
    return conn


class UnownedProvincesTest(unittest.TestCase):
    def test_partial_unowned_assigns_to_highest_tag_and_warns(self) -> None:
        conn = _minimal_conn()
        conn.executemany(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES (?, 1, '', '', '', '', '')",
            [("STATE_TEST",)],
        )
        for prov in ("#aaaaaa", "#bbbbbb", "#cccccc"):
            conn.execute(
                "INSERT INTO ref_sr_prov (state, province) VALUES ('STATE_TEST', ?)",
                (prov,),
            )
        conn.execute("INSERT INTO geo_state (state) VALUES ('STATE_TEST')")
        conn.executemany(
            "INSERT INTO st (state, tag, state_type) VALUES ('STATE_TEST', ?, 'incorporated')",
            [("AAA",), ("ZZZ",)],
        )
        conn.executemany(
            "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_TEST', ?, ?)",
            [("AAA", "#aaaaaa"), ("ZZZ", "#bbbbbb")],
        )

        log = ImportLog()
        _check_unowned_land_provinces(conn, log)

        self.assertTrue(log.ok)
        self.assertEqual(len(log.errors), 0)
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("ZZZ", log.warnings[0])
        self.assertIn("#cccccc", log.warnings[0])
        row = conn.execute(
            "SELECT tag FROM st_prov WHERE province = '#cccccc'"
        ).fetchone()
        self.assertEqual(row[0], "ZZZ")
        conn.close()

    def test_whole_state_unowned_is_error(self) -> None:
        conn = _minimal_conn()
        conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES ('STATE_EMPTY', 2, '', '', '', '', '')"
        )
        conn.execute(
            "INSERT INTO ref_sr_prov (state, province) VALUES ('STATE_EMPTY', '#dddddd')"
        )

        log = ImportLog()
        _check_unowned_land_provinces(conn, log)

        self.assertFalse(log.ok)
        self.assertEqual(len(log.errors), 1)
        self.assertIn("STATE_EMPTY", log.errors[0])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM st_prov").fetchone()[0],
            0,
        )
        conn.close()


if __name__ == "__main__":
    unittest.main()
