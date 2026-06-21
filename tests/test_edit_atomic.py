"""Tests that multi-step macro edits roll back entirely on failure."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.atomic import configure_edit_connection  # noqa: E402
from interactive_map.edit.transfer import (  # noqa: E402
    annex_country,
    tag_has_provinces,
    transfer_state,
)


def _two_state_annex_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    configure_edit_connection(conn)
    conn.executescript(
        """
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
        CREATE TABLE ref_sr_prov (state TEXT NOT NULL, province TEXT NOT NULL, PRIMARY KEY (state, province));
        CREATE TABLE geo_state (state TEXT PRIMARY KEY);
        CREATE TABLE st (state TEXT NOT NULL, tag TEXT NOT NULL, state_type TEXT NOT NULL, PRIMARY KEY (state, tag));
        CREATE TABLE st_prov (
            province TEXT NOT NULL PRIMARY KEY,
            state TEXT NOT NULL,
            tag TEXT NOT NULL
        );
        CREATE TABLE st_pop (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,
            tag TEXT NOT NULL,
            culture TEXT NOT NULL,
            religion TEXT,
            is_slaves INTEGER NOT NULL DEFAULT 0,
            size INTEGER NOT NULL
        );
        CREATE TABLE st_bld (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,
            tag TEXT NOT NULL,
            building TEXT NOT NULL,
            reserves INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    conn.executemany(
        "INSERT INTO ref_tag (tag) VALUES (?)",
        [("AAA",), ("BBB",), ("CCC",)],
    )
    conn.execute("INSERT INTO ref_religion (religion, r, g, b) VALUES ('protestant', 51, 77, 140)")
    conn.execute(
        "INSERT INTO ref_culture (culture, default_religion, r, g, b) VALUES ('british', 'protestant', 210, 156, 140)"
    )
    for idx, state in enumerate(("STATE_A", "STATE_B"), start=1):
        conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES (?, ?, '', '', '', '', '')",
            (state, idx),
        )
        conn.execute("INSERT INTO geo_state (state) VALUES (?)", (state,))
    conn.executemany(
        "INSERT INTO ref_sr_prov (state, province) VALUES (?, ?)",
        [("STATE_A", "x111111"), ("STATE_B", "x222222")],
    )
    conn.executemany(
        "INSERT INTO st (state, tag, state_type) VALUES (?, 'BBB', 'incorporated')",
        [("STATE_A",), ("STATE_B",)],
    )
    conn.executemany(
        "INSERT INTO st_prov (state, tag, province) VALUES (?, 'BBB', ?)",
        [("STATE_A", "x111111"), ("STATE_B", "x222222")],
    )
    conn.commit()
    return conn


def _province_counts(conn: sqlite3.Connection, tag: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM st_prov WHERE tag = ?",
            (tag,),
        ).fetchone()[0]
    )


def _edit_batch_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'edit_batch'"
    ).fetchone()
    if not row or int(row[0]) == 0:
        return 0
    return int(conn.execute("SELECT COUNT(*) FROM edit_batch").fetchone()[0])


class MacroAtomicityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _two_state_annex_conn()

    def tearDown(self) -> None:
        self.conn.close()

    def test_annex_country_rolls_back_on_mid_failure(self) -> None:
        self.assertTrue(tag_has_provinces(self.conn, "BBB"))
        self.assertEqual(_province_counts(self.conn, "BBB"), 2)
        self.assertEqual(_province_counts(self.conn, "AAA"), 0)
        batches_before = _edit_batch_count(self.conn)

        real_transfer = transfer_state
        calls = {"n": 0}

        def failing_transfer(conn, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("injected failure")
            return real_transfer(conn, **kwargs)

        with patch(
            "interactive_map.edit.transfer.transfer_state",
            side_effect=failing_transfer,
        ):
            with self.assertRaises(RuntimeError):
                annex_country(
                    self.conn,
                    origin_tag="BBB",
                    new_tag="AAA",
                    state_type="incorporated",
                )

        self.assertTrue(tag_has_provinces(self.conn, "BBB"))
        self.assertEqual(_province_counts(self.conn, "BBB"), 2)
        self.assertEqual(_province_counts(self.conn, "AAA"), 0)
        self.assertEqual(_edit_batch_count(self.conn), batches_before)

    def test_annex_country_commits_when_all_steps_succeed(self) -> None:
        result = annex_country(
            self.conn,
            origin_tag="BBB",
            new_tag="AAA",
            state_type="incorporated",
        )
        self.conn.commit()
        self.assertEqual(result["states_transferred"], 2)
        self.assertFalse(tag_has_provinces(self.conn, "BBB"))
        self.assertEqual(_province_counts(self.conn, "AAA"), 2)
        self.assertEqual(_edit_batch_count(self.conn), 1)


if __name__ == "__main__":
    unittest.main()
