"""Tests for release country / acquire homelands macro ops."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.country_homeland_macro import (  # noqa: E402
    acquire_all_homelands,
    batch_add_homeland,
    batch_fill_homeland,
    batch_remove_all_homelands,
    batch_remove_homeland,
    list_release_country_candidates,
    load_acquire_homelands_preview,
    load_homeland_batch_macro_preview,
    load_remove_all_homelands_preview,
    release_country,
)
from interactive_map.edit.transfer import tag_has_provinces  # noqa: E402


def _homeland_macro_conn() -> sqlite3.Connection:
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
        CREATE TABLE ref_tag_culture (
            tag TEXT NOT NULL,
            culture TEXT NOT NULL,
            ord INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (tag, culture)
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
        CREATE TABLE geo_state (state TEXT PRIMARY KEY);
        CREATE TABLE geo_homeland (
            state TEXT NOT NULL,
            culture TEXT NOT NULL,
            PRIMARY KEY (state, culture)
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
        CREATE TABLE st_bld (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,
            tag TEXT NOT NULL,
            building TEXT NOT NULL,
            reserves INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    conn.execute("INSERT INTO ref_religion (religion, r, g, b) VALUES ('protestant', 51, 77, 140)")
    conn.executemany(
        "INSERT INTO ref_culture (culture, default_religion) VALUES (?, 'protestant')",
        [("british",), ("scottish",), ("indian",)],
    )
    conn.executemany("INSERT INTO ref_tag (tag) VALUES (?)", [("GBR",), ("AAA",), ("BBB",)])
    conn.executemany(
        "INSERT INTO ref_tag_culture (tag, culture, ord) VALUES (?, ?, ?)",
        [("GBR", "british", 0), ("GBR", "scottish", 1), ("AAA", "british", 0), ("BBB", "indian", 0)],
    )
    for state, sr_id in (("STATE_ENG", 1), ("STATE_SCO", 2), ("STATE_IND", 3)):
        conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES (?, ?, '', '', '', '', '')",
            (state, sr_id),
        )
        conn.execute("INSERT INTO geo_state (state) VALUES (?)", (state,))
    for state, prov in (
        ("STATE_ENG", "x111111"),
        ("STATE_ENG", "x111112"),
        ("STATE_ENG", "x111113"),
        ("STATE_SCO", "x222221"),
        ("STATE_IND", "x333331"),
        ("STATE_IND", "x333332"),
    ):
        conn.execute("INSERT INTO ref_sr_prov (state, province) VALUES (?, ?)", (state, prov))
    conn.executemany(
        "INSERT INTO geo_homeland (state, culture) VALUES (?, ?)",
        [
            ("STATE_ENG", "british"),
            ("STATE_SCO", "scottish"),
            ("STATE_IND", "indian"),
        ],
    )
    conn.executemany(
        "INSERT INTO st (state, tag, state_type) VALUES (?, ?, ?)",
        [
            ("STATE_ENG", "AAA", "incorporated"),
            ("STATE_SCO", "AAA", "incorporated"),
            ("STATE_IND", "AAA", "unincorporated"),
            ("STATE_ENG", "BBB", "incorporated"),
        ],
    )
    conn.executemany(
        "INSERT INTO st_prov (state, tag, province) VALUES (?, ?, ?)",
        [
            ("STATE_ENG", "AAA", "x111111"),
            ("STATE_ENG", "AAA", "x111112"),
            ("STATE_SCO", "AAA", "x222221"),
            ("STATE_IND", "AAA", "x333331"),
            ("STATE_IND", "AAA", "x333332"),
            ("STATE_ENG", "BBB", "x111113"),
        ],
    )
    from interactive_map.edit.atomic import configure_edit_connection

    configure_edit_connection(conn)
    conn.commit()
    return conn


class CountryHomelandMacroTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _homeland_macro_conn()

    def tearDown(self) -> None:
        self.conn.close()

    def test_release_candidates_whitelist(self) -> None:
        candidates = list_release_country_candidates(self.conn, "AAA")
        tags = {item["tag"] for item in candidates}
        self.assertIn("GBR", tags)
        self.assertNotIn("AAA", tags)
        self.assertNotIn("BBB", tags)
        gbr = next(item for item in candidates if item["tag"] == "GBR")
        released_states = {item["state"] for item in gbr["states"]}
        self.assertIn("STATE_ENG", released_states)
        self.assertIn("STATE_SCO", released_states)
        self.assertNotIn("STATE_IND", released_states)

    def test_release_country_transfers_and_incorporates(self) -> None:
        self.assertFalse(tag_has_provinces(self.conn, "GBR"))
        result = release_country(self.conn, tag="AAA", target_tag="GBR")
        self.assertEqual(result["op"], "release_country")
        self.assertTrue(tag_has_provinces(self.conn, "GBR"))
        self.assertTrue(tag_has_provinces(self.conn, "AAA"))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'GBR'"
            ).fetchone()[0],
            3,
        )
        for state in ("STATE_ENG", "STATE_SCO"):
            row = self.conn.execute(
                "SELECT state_type FROM st WHERE tag = 'GBR' AND state = ?",
                (state,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(str(row[0]), "incorporated")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'AAA' AND state = 'STATE_ENG'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'AAA' AND state = 'STATE_IND'"
            ).fetchone()[0],
            2,
        )

    def test_release_country_can_annihilate_releaser(self) -> None:
        self.conn.execute("DELETE FROM st_prov WHERE tag = 'AAA' AND state = 'STATE_IND'")
        self.conn.execute("DELETE FROM st WHERE tag = 'AAA' AND state = 'STATE_IND'")
        result = release_country(self.conn, tag="AAA", target_tag="GBR")
        self.assertEqual(result["op"], "release_country+annex")
        self.assertFalse(tag_has_provinces(self.conn, "AAA"))
        self.assertTrue(tag_has_provinces(self.conn, "GBR"))

    def test_acquire_homelands_takes_foreign_split_states(self) -> None:
        preview = load_acquire_homelands_preview(self.conn, "AAA")
        self.assertEqual(preview["state_count"], 1)
        self.assertEqual(preview["states"][0]["state"], "STATE_ENG")
        result = acquire_all_homelands(self.conn, tag="AAA")
        self.assertEqual(result["op"], "acquire_all_homelands+annex")
        self.assertFalse(tag_has_provinces(self.conn, "BBB"))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'AAA' AND state = 'STATE_ENG'"
            ).fetchone()[0],
            3,
        )
        row = self.conn.execute(
            "SELECT state_type FROM st WHERE tag = 'AAA' AND state = 'STATE_ENG'"
        ).fetchone()
        self.assertEqual(str(row[0]), "incorporated")

    def test_homeland_batch_preview_and_ops(self) -> None:
        preview = load_homeland_batch_macro_preview(self.conn, "AAA")
        self.assertEqual(preview["owned_state_count"], 3)
        removable = {
            item["culture"]: item["state_count"] for item in preview["removable_cultures"]
        }
        self.assertEqual(removable["british"], 1)
        self.assertEqual(removable["scottish"], 1)
        self.assertEqual(removable["indian"], 1)

        removed = batch_remove_homeland(self.conn, tag="AAA", culture="british")
        self.assertEqual(removed["op"], "batch_remove_homeland")
        self.assertEqual(removed["states_updated"], ["STATE_ENG"])
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM geo_homeland WHERE state = 'STATE_ENG' AND culture = 'british'"
            ).fetchone()
        )

        added = batch_add_homeland(self.conn, tag="AAA", culture="british")
        self.assertIn("STATE_ENG", added["states_updated"])
        self.assertIn("STATE_SCO", added["states_updated"])

        self.conn.execute("DELETE FROM geo_homeland WHERE state = 'STATE_IND'")
        preview2 = load_homeland_batch_macro_preview(self.conn, "AAA")
        self.assertEqual(preview2["fillable_state_count"], 1)
        filled = batch_fill_homeland(self.conn, tag="AAA", culture="british")
        self.assertEqual(filled["states_updated"], ["STATE_IND"])
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT 1 FROM geo_homeland WHERE state = 'STATE_IND' AND culture = 'british'"
            ).fetchone()
        )

    def test_homeland_batch_remove_requires_existing_homeland(self) -> None:
        self.conn.execute("DELETE FROM geo_homeland WHERE state = 'STATE_ENG'")
        with self.assertRaises(ValueError):
            batch_remove_homeland(self.conn, tag="AAA", culture="british")

    def test_remove_all_homelands_preview_and_ops(self) -> None:
        preview = load_remove_all_homelands_preview(self.conn, "AAA")
        self.assertEqual(preview["split_state_count"], 1)
        self.assertEqual(preview["include_split"]["owned_state_count"], 3)
        self.assertEqual(preview["include_split"]["states_with_homelands"], 3)
        self.assertEqual(preview["include_split"]["homeland_entry_count"], 3)
        self.assertEqual(preview["exclude_split"]["owned_state_count"], 2)
        self.assertEqual(preview["exclude_split"]["states_with_homelands"], 2)
        self.assertEqual(preview["exclude_split"]["homeland_entry_count"], 2)
        self.assertNotIn("STATE_ENG", preview["exclude_split"]["states"])

        cleared = batch_remove_all_homelands(
            self.conn, tag="AAA", include_split=False
        )
        self.assertEqual(cleared["op"], "batch_remove_all_homelands_exclusive")
        self.assertEqual(set(cleared["states_updated"]), {"STATE_SCO", "STATE_IND"})
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT 1 FROM geo_homeland WHERE state = 'STATE_ENG' AND culture = 'british'"
            ).fetchone()
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM geo_homeland WHERE state = 'STATE_SCO'"
            ).fetchone()
        )

        cleared_all = batch_remove_all_homelands(
            self.conn, tag="AAA", include_split=True
        )
        self.assertEqual(cleared_all["op"], "batch_remove_all_homelands")
        self.assertEqual(cleared_all["states_updated"], ["STATE_ENG"])
        self.assertIsNone(
            self.conn.execute("SELECT 1 FROM geo_homeland WHERE state = 'STATE_ENG'").fetchone()
        )

    def test_remove_all_homelands_empty_scope_raises(self) -> None:
        batch_remove_all_homelands(self.conn, tag="AAA", include_split=True)
        with self.assertRaises(ValueError):
            batch_remove_all_homelands(self.conn, tag="AAA", include_split=True)
        with self.assertRaises(ValueError):
            batch_remove_all_homelands(self.conn, tag="AAA", include_split=False)

    def test_st_prov_enforces_unique_province(self) -> None:
        self.conn.executemany(
            "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_UTAH', ?, ?)",
            [("USA", "xaaaaaa"), ("NAV", "xbbbbbb")],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_UTAH', 'NAV', 'xaaaaaa')"
            )


if __name__ == "__main__":
    unittest.main()
