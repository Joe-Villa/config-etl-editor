"""Tests for state-level geo edits."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.state_geo import (  # noqa: E402
    change_claim,
    change_homeland,
    change_state_type,
    incorporate_all_states,
    load_state_geo_options,
)

DB = ROOT / "output" / "test_map_editor.sqlite"


def _minimal_geo_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE ref_tag (tag TEXT PRIMARY KEY);
        CREATE TABLE ref_culture (
            culture TEXT PRIMARY KEY,
            default_religion TEXT NOT NULL,
            r INTEGER NOT NULL DEFAULT 255,
            g INTEGER NOT NULL DEFAULT 255,
            b INTEGER NOT NULL DEFAULT 255
        );
        CREATE TABLE ref_religion (
            religion TEXT PRIMARY KEY,
            r INTEGER NOT NULL DEFAULT 255,
            g INTEGER NOT NULL DEFAULT 255,
            b INTEGER NOT NULL DEFAULT 255,
            name_zh TEXT NOT NULL DEFAULT '',
            name_en TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE ref_sr (
            state TEXT PRIMARY KEY,
            sr_id INTEGER NOT NULL,
            city TEXT, port TEXT, farm TEXT, mine TEXT, wood TEXT
        );
        CREATE TABLE geo_state (state TEXT PRIMARY KEY);
        CREATE TABLE geo_homeland (
            state TEXT NOT NULL,
            culture TEXT NOT NULL,
            PRIMARY KEY (state, culture)
        );
        CREATE TABLE geo_claim (
            state TEXT NOT NULL,
            claim_tag TEXT NOT NULL,
            PRIMARY KEY (state, claim_tag)
        );
        CREATE TABLE st (
            state TEXT NOT NULL,
            tag TEXT NOT NULL,
            state_type TEXT NOT NULL,
            PRIMARY KEY (state, tag)
        );
        """
    )
    conn.executemany("INSERT INTO ref_tag (tag) VALUES (?)", [("AAA",), ("ZZZ",), ("OLD",)])
    conn.execute("INSERT INTO ref_religion (religion, r, g, b) VALUES ('protestant', 51, 77, 140)")
    conn.execute(
        "INSERT INTO ref_culture (culture, default_religion, r, g, b) VALUES ('british', 'protestant', 210, 156, 140), ('french', 'protestant', 62, 77, 100)",
    )
    conn.execute(
        "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES ('STATE_TEST', 1, '', '', '', '', '')"
    )
    conn.execute("INSERT INTO geo_state (state) VALUES ('STATE_TEST')")
    conn.execute(
        "INSERT INTO st (state, tag, state_type) VALUES ('STATE_TEST', 'AAA', 'incorporated')"
    )
    conn.execute(
        "INSERT INTO geo_homeland (state, culture) VALUES ('STATE_TEST', 'british')"
    )
    conn.execute(
        "INSERT INTO geo_claim (state, claim_tag) VALUES ('STATE_TEST', 'OLD')"
    )
    return conn


class StateGeoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _minimal_geo_conn()

    def tearDown(self) -> None:
        self.conn.close()

    def test_change_state_type(self) -> None:
        result = change_state_type(
            self.conn,
            tag="AAA",
            state="STATE_TEST",
            state_type="unincorporated",
        )
        self.assertEqual(result["after"], "unincorporated")
        row = self.conn.execute(
            "SELECT state_type FROM st WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        ).fetchone()
        self.assertEqual(str(row[0]), "unincorporated")

    def test_incorporate_all_states(self) -> None:
        self.conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES ('STATE_OTHER', 2, '', '', '', '', '')"
        )
        self.conn.execute(
            "INSERT INTO st (state, tag, state_type) VALUES ('STATE_OTHER', 'AAA', 'unincorporated')"
        )
        result = incorporate_all_states(self.conn, tag="AAA")
        self.assertEqual(result["op"], "incorporate_all_states")
        self.assertEqual(result["states_updated"], ["STATE_OTHER"])
        rows = self.conn.execute(
            "SELECT state, state_type FROM st WHERE tag = 'AAA' ORDER BY state"
        ).fetchall()
        self.assertEqual(
            [(str(s), str(t)) for s, t in rows],
            [("STATE_OTHER", "incorporated"), ("STATE_TEST", "incorporated")],
        )

    def test_incorporate_all_states_already_done(self) -> None:
        with self.assertRaises(ValueError):
            incorporate_all_states(self.conn, tag="AAA")

    def test_change_homeland_add_remove(self) -> None:
        change_homeland(
            self.conn,
            state="STATE_TEST",
            culture="french",
            action="add",
        )
        cultures = {
            row[0]
            for row in self.conn.execute(
                "SELECT culture FROM geo_homeland WHERE state = 'STATE_TEST'"
            )
        }
        self.assertEqual(cultures, {"british", "french"})
        change_homeland(
            self.conn,
            state="STATE_TEST",
            culture="british",
            action="remove",
        )
        cultures = {
            row[0]
            for row in self.conn.execute(
                "SELECT culture FROM geo_homeland WHERE state = 'STATE_TEST'"
            )
        }
        self.assertEqual(cultures, {"french"})

    def test_change_claim_allows_inactive_tag(self) -> None:
        change_claim(
            self.conn,
            state="STATE_TEST",
            claim_tag="ZZZ",
            action="add",
        )
        claims = [
            str(row[0])
            for row in self.conn.execute(
                "SELECT claim_tag FROM geo_claim WHERE state = 'STATE_TEST' ORDER BY claim_tag"
            )
        ]
        self.assertEqual(claims, ["OLD", "ZZZ"])

    def test_load_state_geo_options(self) -> None:
        opts = load_state_geo_options(self.conn, "AAA", "STATE_TEST")
        self.assertEqual(opts["state_type"], "incorporated")
        self.assertIn("british", opts["homelands"])
        self.assertIn("OLD", opts["claims"])
        self.assertIn("french", opts["cultures"])
        self.assertIn("ZZZ", opts["claim_tags"])


@unittest.skipUnless(DB.is_file(), "需要 test_map_editor.sqlite")
class StateGeoIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = sqlite3.connect(DB)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_options_from_real_db(self) -> None:
        row = self.conn.execute(
            "SELECT tag, state FROM st LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(row)
        opts = load_state_geo_options(self.conn, str(row[0]), str(row[1]))
        self.assertIn("cultures", opts)
        self.assertIn("claim_tags", opts)


if __name__ == "__main__":
    unittest.main()
