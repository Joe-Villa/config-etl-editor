"""Tests for country-level batch pop culture / religion conversion."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.country_pop_macro import (  # noqa: E402
    RELIGION_DEFAULT_SENTINEL,
    batch_convert_culture,
    batch_convert_religion,
    load_pop_convert_macro_preview,
)


def _pop_macro_conn():
    import sqlite3

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
        CREATE TABLE ref_sr_prov (
            state TEXT NOT NULL,
            province TEXT NOT NULL,
            PRIMARY KEY (state, province)
        );
        CREATE TABLE st (
            state TEXT NOT NULL,
            tag TEXT NOT NULL,
            state_type TEXT NOT NULL,
            PRIMARY KEY (state, tag)
        );
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
        """
    )
    from interactive_map.edit.atomic import configure_edit_connection
    from interactive_map.edit.log import ensure_edit_schema

    configure_edit_connection(conn)
    ensure_edit_schema(conn)
    conn.executemany(
        "INSERT INTO ref_religion (religion, r, g, b) VALUES (?, 1, 2, 3)",
        [("shinto",), ("buddhist",), ("protestant",)],
    )
    conn.executemany(
        "INSERT INTO ref_culture (culture, default_religion) VALUES (?, ?)",
        [("han", "shinto"), ("british", "protestant")],
    )
    conn.execute("INSERT INTO ref_tag (tag) VALUES ('USA')")
    conn.execute(
        "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) "
        "VALUES ('STATE_CAL', 1, '', '', '', '', '')"
    )
    conn.execute(
        "INSERT INTO st (state, tag, state_type) VALUES ('STATE_CAL', 'USA', 'incorporated')"
    )
    conn.execute(
        "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_CAL', 'USA', 'x111111')"
    )
    conn.commit()
    return conn


class CountryPopMacroTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _pop_macro_conn()

    def tearDown(self) -> None:
        self.conn.close()

    def _insert_pop(
        self,
        *,
        culture: str,
        religion: str | None,
        is_slaves: bool,
        size: int,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO st_pop (state, tag, culture, religion, is_slaves, size)
            VALUES ('STATE_CAL', 'USA', ?, ?, ?, ?)
            """,
            (culture, religion, int(is_slaves), size),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def test_preview_lists_only_present_cultures_and_religions(self) -> None:
        self._insert_pop(culture="han", religion="shinto", is_slaves=False, size=100)
        self._insert_pop(culture="han", religion=None, is_slaves=False, size=50)
        preview = load_pop_convert_macro_preview(self.conn, "USA")
        cultures = {item["culture"] for item in preview["convertible_cultures"]}
        self.assertEqual(cultures, {"han"})
        religion_keys = {item["religion_key"] for item in preview["convertible_religions"]}
        self.assertEqual(religion_keys, {"shinto", RELIGION_DEFAULT_SENTINEL})

    def test_convert_culture_merges_same_target_scope(self) -> None:
        self._insert_pop(culture="han", religion="shinto", is_slaves=False, size=100)
        self._insert_pop(culture="han", religion="buddhist", is_slaves=False, size=200)
        self._insert_pop(culture="han", religion="shinto", is_slaves=True, size=30)

        result = batch_convert_culture(
            self.conn,
            tag="USA",
            from_culture="han",
            to_culture="british",
        )
        self.assertEqual(result["op"], "batch_convert_culture")
        rows = self.conn.execute(
            """
            SELECT culture, religion, is_slaves, size
            FROM st_pop WHERE tag = 'USA'
            ORDER BY is_slaves, religion
            """
        ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            rows,
            [
                ("british", "buddhist", 0, 200),
                ("british", "shinto", 0, 100),
                ("british", "shinto", 1, 30),
            ],
        )

    def test_convert_religion_merges_into_existing_target_pop(self) -> None:
        self._insert_pop(culture="han", religion="shinto", is_slaves=False, size=100)
        self._insert_pop(culture="han", religion="buddhist", is_slaves=False, size=40)
        self._insert_pop(culture="han", religion="buddhist", is_slaves=False, size=60)

        result = batch_convert_religion(
            self.conn,
            tag="USA",
            from_religion="shinto",
            to_religion="buddhist",
        )
        self.assertEqual(result["op"], "batch_convert_religion")
        rows = self.conn.execute(
            "SELECT culture, religion, is_slaves, size FROM st_pop WHERE tag = 'USA'"
        ).fetchall()
        self.assertEqual(rows, [("han", "buddhist", 0, 200)])

    def test_convert_religion_from_culture_default(self) -> None:
        self._insert_pop(culture="han", religion=None, is_slaves=False, size=80)
        self._insert_pop(culture="han", religion="buddhist", is_slaves=False, size=20)

        batch_convert_religion(
            self.conn,
            tag="USA",
            from_religion=None,
            to_religion="protestant",
        )
        rows = self.conn.execute(
            "SELECT religion, size FROM st_pop WHERE tag = 'USA' ORDER BY size"
        ).fetchall()
        self.assertEqual(rows, [("buddhist", 20), ("protestant", 80)])

    def test_convert_culture_requires_source_pops(self) -> None:
        self._insert_pop(culture="british", religion="protestant", is_slaves=False, size=10)
        with self.assertRaises(ValueError):
            batch_convert_culture(
                self.conn,
                tag="USA",
                from_culture="han",
                to_culture="british",
            )


if __name__ == "__main__":
    unittest.main()
