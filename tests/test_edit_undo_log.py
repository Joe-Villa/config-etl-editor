"""Edit log must record undo_json for every write operation."""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.atomic import configure_edit_connection  # noqa: E402
from interactive_map.edit.buildings import add_building, delete_building, update_building  # noqa: E402
from interactive_map.edit.country_homeland_macro import (  # noqa: E402
    acquire_all_homelands,
    release_country,
)
from interactive_map.edit.log import ensure_edit_schema  # noqa: E402
from interactive_map.edit.pops import add_pop, delete_pop, update_pop  # noqa: E402
from interactive_map.edit.state_geo import (  # noqa: E402
    change_claim,
    change_homeland,
    change_state_type,
    incorporate_all_states,
)
from interactive_map.edit.transfer import (  # noqa: E402
    annex_country,
    annex_country_into,
    change_tag,
    expand_all_split_states,
    expand_scope_to_full_state,
    set_owner,
    transfer_province,
    transfer_state,
)


def _undo_rows(conn: sqlite3.Connection, batch_id: int) -> list[object | None]:
    ensure_edit_schema(conn)
    return [
        json.loads(row[0]) if row[0] is not None else None
        for row in conn.execute(
            "SELECT undo_json FROM edit_log WHERE batch_id = ? ORDER BY ord",
            (batch_id,),
        )
    ]


def _assert_batch_has_undo(test: unittest.TestCase, conn: sqlite3.Connection, batch_id: int) -> None:
    undos = _undo_rows(conn, batch_id)
    test.assertTrue(undos, "batch has no edit_log steps")
    for undo in undos:
        test.assertIsNotNone(undo, "edit_log step missing undo_json")


def _base_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    configure_edit_connection(conn)
    conn.executescript(
        """
        CREATE TABLE ref_tag (tag TEXT PRIMARY KEY);
        CREATE TABLE ref_tag_culture (tag TEXT NOT NULL, ord INTEGER NOT NULL, culture TEXT NOT NULL, PRIMARY KEY (tag, ord));
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
        CREATE TABLE geo_homeland (state TEXT NOT NULL, culture TEXT NOT NULL, PRIMARY KEY (state, culture));
        CREATE TABLE geo_claim (state TEXT NOT NULL, claim_tag TEXT NOT NULL, PRIMARY KEY (state, claim_tag));
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
        [("AAA",), ("BBB",), ("CCC",), ("DDD",)],
    )
    conn.executemany(
        "INSERT INTO ref_tag_culture (tag, ord, culture) VALUES (?, 0, ?)",
        [("AAA", "british"), ("BBB", "french"), ("CCC", "british"), ("DDD", "german")],
    )
    conn.execute("INSERT INTO ref_religion (religion, r, g, b) VALUES ('protestant', 51, 77, 140)")
    conn.executemany(
        "INSERT INTO ref_culture (culture, default_religion, r, g, b) VALUES (?, 'protestant', 200, 180, 160)",
        [("british",), ("french",), ("german",)],
    )
    conn.execute(
        "INSERT INTO ref_bld (building, building_group, buildable) VALUES ('iron_mine', 'mining', 1)"
    )
    conn.execute("INSERT INTO ref_bg (building_group, root_group) VALUES ('mining', 'mining')")
    conn.execute("INSERT INTO ref_pmg (pm_group) VALUES ('pmg_mining')")
    conn.execute(
        "INSERT INTO ref_bld_pmg (building, ord, pm_group) VALUES ('iron_mine', 0, 'pmg_mining')"
    )
    conn.execute(
        "INSERT INTO ref_pmg_pm (pm_group, ord, pm) VALUES ('pmg_mining', 0, 'pm_iron')"
    )
    for idx, state in enumerate(("STATE_A", "STATE_B", "STATE_C"), start=1):
        conn.execute(
            "INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood) VALUES (?, ?, '', '', '', '', '')",
            (state, idx),
        )
        conn.execute("INSERT INTO geo_state (state) VALUES (?)", (state,))
        conn.execute(
            "INSERT INTO geo_homeland (state, culture) VALUES (?, 'british')",
            (state,),
        )
    conn.executemany(
        "INSERT INTO ref_sr_prov (state, province) VALUES (?, ?)",
        [
            ("STATE_A", "x111111"),
            ("STATE_A", "x111112"),
            ("STATE_B", "x222221"),
            ("STATE_B", "x222222"),
            ("STATE_C", "x333331"),
            ("STATE_C", "x333332"),
        ],
    )
    conn.executemany(
        "INSERT INTO st (state, tag, state_type) VALUES (?, ?, ?)",
        [
            ("STATE_A", "AAA", "incorporated"),
            ("STATE_A", "BBB", "unincorporated"),
            ("STATE_B", "BBB", "incorporated"),
            ("STATE_C", "AAA", "incorporated"),
            ("STATE_C", "CCC", "unincorporated"),
        ],
    )
    conn.executemany(
        "INSERT INTO st_prov (state, tag, province) VALUES (?, ?, ?)",
        [
            ("STATE_A", "AAA", "x111111"),
            ("STATE_A", "BBB", "x111112"),
            ("STATE_B", "BBB", "x222221"),
            ("STATE_B", "BBB", "x222222"),
            ("STATE_C", "AAA", "x333331"),
            ("STATE_C", "CCC", "x333332"),
        ],
    )
    conn.commit()
    return conn


class EditUndoLogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = _base_conn()

    def tearDown(self) -> None:
        self.conn.close()

    def test_building_ops_log_undo(self) -> None:
        created = add_building(
            self.conn,
            tag="BBB",
            state="STATE_B",
            building="iron_mine",
            pms=["pm_iron"],
        )
        _assert_batch_has_undo(self, self.conn, int(created["batch_id"]))

        updated = update_building(
            self.conn,
            tag="BBB",
            state="STATE_B",
            bld_id=int(created["bld_id"]),
            pms=["pm_iron"],
            level=2,
        )
        _assert_batch_has_undo(self, self.conn, int(updated["batch_id"]))

        deleted = delete_building(
            self.conn,
            tag="BBB",
            state="STATE_B",
            bld_id=int(created["bld_id"]),
        )
        _assert_batch_has_undo(self, self.conn, int(deleted["batch_id"]))

    def test_pop_ops_log_undo(self) -> None:
        created = add_pop(
            self.conn,
            tag="BBB",
            state="STATE_B",
            culture="french",
            size=5000,
        )
        _assert_batch_has_undo(self, self.conn, int(created["batch_id"]))

        updated = update_pop(
            self.conn,
            tag="BBB",
            state="STATE_B",
            pop_id=int(created["pop_id"]),
            culture="french",
            size=6000,
        )
        _assert_batch_has_undo(self, self.conn, int(updated["batch_id"]))

        deleted = delete_pop(
            self.conn,
            tag="BBB",
            state="STATE_B",
            pop_id=int(created["pop_id"]),
        )
        _assert_batch_has_undo(self, self.conn, int(deleted["batch_id"]))

    def test_state_geo_ops_log_undo(self) -> None:
        typed = change_state_type(
            self.conn, tag="BBB", state="STATE_B", state_type="unincorporated"
        )
        _assert_batch_has_undo(self, self.conn, int(typed["batch_id"]))

        homeland = change_homeland(
            self.conn, state="STATE_A", culture="german", action="add"
        )
        _assert_batch_has_undo(self, self.conn, int(homeland["batch_id"]))

        claim = change_claim(self.conn, state="STATE_A", claim_tag="DDD", action="add")
        _assert_batch_has_undo(self, self.conn, int(claim["batch_id"]))

        incorporated = incorporate_all_states(self.conn, tag="BBB")
        _assert_batch_has_undo(self, self.conn, int(incorporated["batch_id"]))

    def test_transfer_ops_log_undo(self) -> None:
        owner = set_owner(self.conn, province_hex="#111111", new_tag="CCC")
        _assert_batch_has_undo(self, self.conn, int(owner["batch_id"]))

        province = transfer_province(
            self.conn, province_hex="#222221", new_tag="AAA", origin_tag="BBB"
        )
        _assert_batch_has_undo(self, self.conn, int(province["batch_id"]))

        state = transfer_state(
            self.conn, state="STATE_B", origin_tag="BBB", new_tag="AAA"
        )
        _assert_batch_has_undo(self, self.conn, int(state["batch_id"]))

        expanded = expand_scope_to_full_state(
            self.conn, tag="AAA", state="STATE_A"
        )
        _assert_batch_has_undo(self, self.conn, int(expanded["batch_id"]))

        annexed = annex_country(
            self.conn, origin_tag="CCC", new_tag="AAA", state_type="incorporated"
        )
        _assert_batch_has_undo(self, self.conn, int(annexed["batch_id"]))

    def test_annex_into_and_change_tag_log_undo(self) -> None:
        merged = annex_country_into(
            self.conn, acquirer_tag="AAA", victim_tag="BBB", force_unincorporated=True
        )
        _assert_batch_has_undo(self, self.conn, int(merged["batch_id"]))

        changed = change_tag(self.conn, old_tag="AAA", new_tag="DDD")
        _assert_batch_has_undo(self, self.conn, int(changed["batch_id"]))

    def test_expand_all_split_states_log_undo(self) -> None:
        expanded = expand_all_split_states(self.conn, tag="AAA")
        _assert_batch_has_undo(self, self.conn, int(expanded["batch_id"]))

    def test_release_country_log_undo(self) -> None:
        self.conn.execute("INSERT INTO ref_tag (tag) VALUES ('EEE')")
        self.conn.execute(
            "INSERT INTO ref_tag_culture (tag, ord, culture) VALUES ('EEE', 0, 'british')"
        )
        self.conn.commit()

        released = release_country(self.conn, tag="AAA", target_tag="EEE")
        _assert_batch_has_undo(self, self.conn, int(released["batch_id"]))

    def test_acquire_all_homelands_log_undo(self) -> None:
        acquired = acquire_all_homelands(self.conn, tag="AAA")
        _assert_batch_has_undo(self, self.conn, int(acquired["batch_id"]))


if __name__ == "__main__":
    unittest.main()
