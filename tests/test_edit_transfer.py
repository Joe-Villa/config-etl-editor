"""Tests for province / state / country transfer."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.buildings import (  # noqa: E402
    add_building,
    resolve_owner_tag_for_export,
)
from interactive_map.edit.pops import add_pop  # noqa: E402
from interactive_map.edit.transfer import (  # noqa: E402
    annex_country,
    annex_country_into,
    change_tag,
    expand_all_split_states,
    expand_scope_to_full_state,
    find_province_owner,
    list_split_states_for_tag,
    load_state_expansion_preview,
    tag_has_provinces,
    transfer_province,
    transfer_scope_state,
    transfer_state,
)
from interactive_map.foreign_investment import compute_foreign_by_scope  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


def _minimal_transfer_conn() -> sqlite3.Connection:
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
        CREATE TABLE ref_bld (
            building TEXT PRIMARY KEY,
            building_group TEXT NOT NULL,
            buildable INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE ref_bg (building_group TEXT PRIMARY KEY, root_group TEXT NOT NULL);
        CREATE TABLE ref_bld_pmg (building TEXT NOT NULL, ord INTEGER NOT NULL, pm_group TEXT NOT NULL, PRIMARY KEY (building, ord));
        CREATE TABLE ref_pmg (pm_group TEXT PRIMARY KEY);
        CREATE TABLE ref_pmg_pm (pm_group TEXT NOT NULL, ord INTEGER NOT NULL, pm TEXT NOT NULL, PRIMARY KEY (pm_group, ord));
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
        CREATE UNIQUE INDEX uq_st_pop ON st_pop (
            state, tag, culture, IFNULL(religion, ''), is_slaves
        );
        CREATE TABLE st_bld (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,
            tag TEXT NOT NULL,
            building TEXT NOT NULL,
            reserves INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE st_bld_own (
            bld_id INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            ownership TEXT NOT NULL,
            level INTEGER NOT NULL,
            owner_tag TEXT NOT NULL DEFAULT '',
            owner_state TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (bld_id, ord),
            FOREIGN KEY (bld_id) REFERENCES st_bld (id) ON DELETE CASCADE
        );
        CREATE TABLE st_bld_pm (
            bld_id INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            pm TEXT NOT NULL,
            PRIMARY KEY (bld_id, ord),
            FOREIGN KEY (bld_id) REFERENCES st_bld (id) ON DELETE CASCADE
        );
        """
    )
    conn.executemany(
        "INSERT INTO ref_tag (tag) VALUES (?)",
        [("AAA",), ("BBB",), ("CCC",), ("GBR",)],
    )
    conn.execute("INSERT INTO ref_religion (religion, r, g, b) VALUES ('protestant', 51, 77, 140)")
    conn.execute(
        "INSERT INTO ref_culture (culture, default_religion, r, g, b) VALUES ('british', 'protestant', 210, 156, 140)",
    )
    conn.execute(
        "INSERT INTO ref_bg (building_group, root_group) VALUES ('bg_government', 'bg_government')"
    )
    conn.execute(
        """
        INSERT INTO ref_bld (building, building_group, buildable)
        VALUES ('building_university', 'bg_government', 1)
        """
    )
    conn.execute("INSERT INTO ref_pmg (pm_group) VALUES ('pmg_default')")
    conn.execute(
        "INSERT INTO ref_bld_pmg (building, ord, pm_group) VALUES ('building_university', 0, 'pmg_default')"
    )
    conn.execute(
        "INSERT INTO ref_pmg_pm (pm_group, ord, pm) VALUES ('pmg_default', 0, 'pm_default')"
    )
    conn.execute(
        "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES ('STATE_TEST', 1, '', '', '', '', '')"
    )
    for prov in ("xAAAAAA", "xBBBBBB", "xCCCCCC"):
        conn.execute(
            "INSERT INTO ref_sr_prov (state, province) VALUES ('STATE_TEST', ?)",
            (prov,),
        )
    conn.execute("INSERT INTO geo_state (state) VALUES ('STATE_TEST')")
    conn.executemany(
        "INSERT INTO st (state, tag, state_type) VALUES ('STATE_TEST', ?, 'incorporated')",
        [("AAA",), ("BBB",)],
    )
    conn.executemany(
        "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_TEST', ?, ?)",
        [("AAA", "xAAAAAA"), ("AAA", "xBBBBBB"), ("BBB", "xCCCCCC")],
    )
    return conn


class TransferMinimalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _minimal_transfer_conn()

    def tearDown(self) -> None:
        self.conn.close()

    def test_partial_province_transfer(self) -> None:
        result = transfer_province(
            self.conn,
            province_hex="#aaaaaa",
            new_tag="CCC",
            origin_tag="AAA",
        )
        self.assertEqual(result["op"], "province_transfer")
        self.assertEqual(result["province"], "#aaaaaa")
        self.assertEqual(find_province_owner(self.conn, "#aaaaaa"), ("STATE_TEST", "CCC"))
        owner_db = self.conn.execute(
            "SELECT tag FROM st_prov WHERE province = 'xAAAAAA'"
        ).fetchone()
        self.assertEqual(str(owner_db[0]), "CCC")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'AAA' AND state = 'STATE_TEST'"
            ).fetchone()[0],
            1,
        )
        aaa_st = self.conn.execute(
            "SELECT 1 FROM st WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        ).fetchone()
        self.assertIsNotNone(aaa_st)

    def test_state_transfer_on_last_province(self) -> None:
        self.conn.execute(
            """
            INSERT INTO st_pop (state, tag, culture, religion, is_slaves, size)
            VALUES ('STATE_TEST', 'BBB', 'british', NULL, 0, 5000)
            """
        )
        add_building(
            self.conn,
            tag="BBB",
            state="STATE_TEST",
            building="building_university",
            pms=None,
            ownership_type="country",
        )
        result = transfer_province(
            self.conn,
            province_hex="#cccccc",
            new_tag="AAA",
            origin_tag="BBB",
        )
        self.assertIn(result["op"], ("state_transfer", "state_transfer+annex"))
        self.assertIsNone(
            self.conn.execute(
                "SELECT 1 FROM st WHERE tag = 'BBB' AND state = 'STATE_TEST'"
            ).fetchone()
        )
        pop_row = self.conn.execute(
            "SELECT size FROM st_pop WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        ).fetchone()
        self.assertIsNotNone(pop_row)
        self.assertEqual(int(pop_row[0]), 5000)
        bld_row = self.conn.execute(
            "SELECT tag FROM st_bld WHERE state = 'STATE_TEST'"
        ).fetchone()
        self.assertEqual(str(bld_row[0]), "AAA")

    def test_pop_merge_when_target_has_state(self) -> None:
        self.conn.execute(
            """
            INSERT INTO st_pop (state, tag, culture, religion, is_slaves, size)
            VALUES ('STATE_TEST', 'AAA', 'british', NULL, 0, 1000),
                   ('STATE_TEST', 'BBB', 'british', NULL, 0, 2000)
            """
        )
        transfer_state(
            self.conn,
            state="STATE_TEST",
            origin_tag="BBB",
            new_tag="AAA",
        )
        rows = self.conn.execute(
            "SELECT size FROM st_pop WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0][0]), 3000)

    def test_transfer_scope_state_moves_all_provinces(self) -> None:
        self.conn.execute(
            """
            INSERT INTO st_pop (state, tag, culture, religion, is_slaves, size)
            VALUES ('STATE_TEST', 'AAA', 'british', NULL, 0, 8000)
            """
        )
        result = transfer_scope_state(
            self.conn,
            tag="AAA",
            state="STATE_TEST",
            new_tag="CCC",
        )
        self.assertIn(result["op"], ("state_transfer", "state_transfer+annex"))
        self.assertEqual(result["provinces_moved"], 2)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'AAA' AND state = 'STATE_TEST'"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'CCC' AND state = 'STATE_TEST'"
            ).fetchone()[0],
            2,
        )
        pop_row = self.conn.execute(
            "SELECT size FROM st_pop WHERE tag = 'CCC' AND state = 'STATE_TEST'"
        ).fetchone()
        self.assertIsNotNone(pop_row)
        self.assertEqual(int(pop_row[0]), 8000)

    def test_expansion_preview_split_state(self) -> None:
        preview = load_state_expansion_preview(self.conn, "AAA", "STATE_TEST")
        self.assertTrue(preview["is_split"])
        self.assertEqual(preview["owned_province_count"], 2)
        self.assertEqual(preview["other_province_count"], 1)
        self.assertEqual(len(preview["other_tags"]), 1)
        self.assertEqual(preview["other_tags"][0]["tag"], "BBB")
        self.assertTrue(preview["other_tags"][0]["would_annex"])

    def test_expand_scope_to_full_state(self) -> None:
        self.conn.execute(
            """
            INSERT INTO st_pop (state, tag, culture, religion, is_slaves, size)
            VALUES ('STATE_TEST', 'BBB', 'british', NULL, 0, 3000)
            """
        )
        result = expand_scope_to_full_state(
            self.conn,
            tag="AAA",
            state="STATE_TEST",
        )
        self.assertIn(result["op"], ("expand_to_full_state", "expand_to_full_state+annex"))
        self.assertEqual(result["provinces_moved"], 1)
        self.assertEqual(result["annexed_tags"], ["BBB"])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE state = 'STATE_TEST' AND tag = 'AAA'"
            ).fetchone()[0],
            3,
        )
        self.assertFalse(tag_has_provinces(self.conn, "BBB"))
        pop_row = self.conn.execute(
            "SELECT size FROM st_pop WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        ).fetchone()
        self.assertIsNotNone(pop_row)
        self.assertEqual(int(pop_row[0]), 3000)
        st_type = self.conn.execute(
            "SELECT state_type FROM st WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        ).fetchone()[0]
        self.assertEqual(str(st_type), "incorporated")

    def test_expand_other_tag_keeps_other_states(self) -> None:
        self.conn.execute(
            "INSERT INTO geo_state (state) VALUES ('STATE_OTHER')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES ('STATE_OTHER', 2, '', '', '', '', '')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr_prov (state, province) VALUES ('STATE_OTHER', 'xDDDDDD')"
        )
        self.conn.execute(
            "INSERT INTO st (state, tag, state_type) VALUES ('STATE_OTHER', 'BBB', 'incorporated')"
        )
        self.conn.execute(
            "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_OTHER', 'BBB', 'xDDDDDD')"
        )
        preview = load_state_expansion_preview(self.conn, "AAA", "STATE_TEST")
        bbb = next(item for item in preview["other_tags"] if item["tag"] == "BBB")
        self.assertFalse(bbb["would_annex"])
        result = expand_scope_to_full_state(
            self.conn, tag="AAA", state="STATE_TEST"
        )
        self.assertEqual(result["annexed_tags"], [])
        self.assertTrue(tag_has_provinces(self.conn, "BBB"))

    def test_expand_already_full_raises(self) -> None:
        expand_scope_to_full_state(self.conn, tag="AAA", state="STATE_TEST")
        with self.assertRaises(ValueError):
            expand_scope_to_full_state(self.conn, tag="AAA", state="STATE_TEST")

    def test_annex_rewrites_foreign_investment(self) -> None:
        self.conn.execute(
            "INSERT INTO geo_state (state) VALUES ('STATE_OTHER')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES ('STATE_OTHER', 2, '', '', '', '', '')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr_prov (state, province) VALUES ('STATE_OTHER', 'xDDDDDD')"
        )
        self.conn.executemany(
            "INSERT INTO st (state, tag, state_type) VALUES (?, ?, 'incorporated')",
            [("STATE_OTHER", "AAA"),],
        )
        self.conn.execute(
            "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_OTHER', 'AAA', 'xDDDDDD')",
        )
        add_building(
            self.conn,
            tag="AAA",
            state="STATE_OTHER",
            building="building_university",
            pms=None,
            ownership_type="country",
            owner_tag="BBB",
        )
        before = compute_foreign_by_scope(self.conn)
        self.assertEqual(before.get(("AAA", "STATE_OTHER"), 0), 1)

        transfer_province(
            self.conn,
            province_hex="#cccccc",
            new_tag="AAA",
            origin_tag="BBB",
        )
        self.assertFalse(
            self.conn.execute("SELECT 1 FROM st_prov WHERE tag = 'BBB'").fetchone()
        )
        after = compute_foreign_by_scope(self.conn)
        self.assertEqual(after.get(("AAA", "STATE_OTHER"), 0), 0)
        bld_id = self.conn.execute("SELECT id FROM st_bld").fetchone()[0]
        owner_tag = self.conn.execute(
            "SELECT owner_tag FROM st_bld_own WHERE bld_id = ?", (bld_id,)
        ).fetchone()[0]
        scope_tag = self.conn.execute(
            "SELECT tag FROM st_bld WHERE id = ?", (bld_id,)
        ).fetchone()[0]
        self.assertEqual(
            resolve_owner_tag_for_export(str(scope_tag), str(owner_tag)),
            "AAA",
        )

    def test_expand_all_split_states(self) -> None:
        self.assertEqual(list_split_states_for_tag(self.conn, "AAA"), ["STATE_TEST"])
        result = expand_all_split_states(self.conn, tag="AAA")
        self.assertIn(
            result["op"],
            ("expand_all_split_states", "expand_all_split_states+annex"),
        )
        self.assertEqual(result["states_expanded"], ["STATE_TEST"])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'AAA' AND state = 'STATE_TEST'"
            ).fetchone()[0],
            3,
        )
        self.assertFalse(tag_has_provinces(self.conn, "BBB"))

    def test_annex_preserve_keeps_acquirer_split_state_type(self) -> None:
        self.conn.execute(
            "UPDATE st SET state_type = 'unincorporated' WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        )
        self.conn.execute(
            "INSERT INTO geo_state (state) VALUES ('STATE_OTHER')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES ('STATE_OTHER', 2, '', '', '', '', '')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr_prov (state, province) VALUES ('STATE_OTHER', 'xDDDDDD')"
        )
        self.conn.execute(
            "INSERT INTO st (state, tag, state_type) VALUES ('STATE_OTHER', 'BBB', 'incorporated')"
        )
        self.conn.execute(
            "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_OTHER', 'BBB', 'xDDDDDD')"
        )
        self.conn.execute(
            "INSERT INTO st (state, tag, state_type) VALUES ('STATE_OTHER', 'AAA', 'unincorporated')"
        )
        self.conn.execute(
            "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_OTHER', 'AAA', 'xEEEEEE')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr_prov (state, province) VALUES ('STATE_OTHER', 'xEEEEEE')"
        )
        result = annex_country_into(
            self.conn,
            acquirer_tag="AAA",
            victim_tag="BBB",
            force_unincorporated=False,
        )
        self.assertEqual(result["op"], "annex_country_preserve")
        aaa_type = self.conn.execute(
            "SELECT state_type FROM st WHERE tag = 'AAA' AND state = 'STATE_OTHER'"
        ).fetchone()[0]
        self.assertEqual(str(aaa_type), "unincorporated")
        test_type = self.conn.execute(
            "SELECT state_type FROM st WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        ).fetchone()[0]
        self.assertEqual(str(test_type), "unincorporated")

    def test_annex_unincorporated_only_new_states(self) -> None:
        self.conn.execute(
            "INSERT INTO geo_state (state) VALUES ('STATE_OTHER')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES ('STATE_OTHER', 2, '', '', '', '', '')"
        )
        self.conn.execute(
            "INSERT INTO ref_sr_prov (state, province) VALUES ('STATE_OTHER', 'xDDDDDD')"
        )
        self.conn.execute(
            "INSERT INTO st (state, tag, state_type) VALUES ('STATE_OTHER', 'BBB', 'incorporated')"
        )
        self.conn.execute(
            "INSERT INTO st_prov (state, tag, province) VALUES ('STATE_OTHER', 'BBB', 'xDDDDDD')"
        )
        result = annex_country_into(
            self.conn,
            acquirer_tag="AAA",
            victim_tag="BBB",
            force_unincorporated=True,
        )
        self.assertEqual(result["op"], "annex_country_unincorporated")
        other_type = self.conn.execute(
            "SELECT state_type FROM st WHERE tag = 'AAA' AND state = 'STATE_OTHER'"
        ).fetchone()[0]
        self.assertEqual(str(other_type), "unincorporated")
        test_type = self.conn.execute(
            "SELECT state_type FROM st WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        ).fetchone()[0]
        self.assertEqual(str(test_type), "incorporated")

    def test_change_tag_to_inactive(self) -> None:
        self.conn.execute(
            "UPDATE st SET state_type = 'unincorporated' WHERE tag = 'AAA' AND state = 'STATE_TEST'"
        )
        result = change_tag(self.conn, old_tag="AAA", new_tag="CCC")
        self.assertEqual(result["op"], "change_tag")
        self.assertFalse(tag_has_provinces(self.conn, "AAA"))
        self.assertTrue(tag_has_provinces(self.conn, "CCC"))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM st_prov WHERE tag = 'CCC' AND state = 'STATE_TEST'"
            ).fetchone()[0],
            2,
        )
        st_type = self.conn.execute(
            "SELECT state_type FROM st WHERE tag = 'CCC' AND state = 'STATE_TEST'"
        ).fetchone()[0]
        self.assertEqual(str(st_type), "unincorporated")
        self.assertIsNone(
            self.conn.execute("SELECT 1 FROM st WHERE tag = 'AAA'").fetchone()
        )

    def test_change_tag_rejects_active_target(self) -> None:
        with self.assertRaises(ValueError):
            change_tag(self.conn, old_tag="AAA", new_tag="BBB")


@unittest.skipUnless(DB.is_file(), "需要 test_map_editor.sqlite")
class TransferIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.conn = sqlite3.connect(DB)
        cls.conn.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()

    def test_load_transfer_options_via_db(self) -> None:
        from interactive_map.edit.transfer import load_transfer_options

        opts = load_transfer_options(self.conn)
        self.assertIn("tags", opts)
        self.assertIn("active_tags", opts)
        self.assertGreater(len(opts["tags"]), len(opts["active_tags"]))


if __name__ == "__main__":
    unittest.main()
