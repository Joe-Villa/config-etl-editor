"""Tests for building edit operations."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.buildings import (  # noqa: E402
    BUILDING_LEVEL_ERROR,
    _normalize_ownership_for_scope,
    add_building,
    delete_building,
    load_building_options,
    parse_building_level,
    update_building,
)

DB = ROOT / "output" / "test_map_editor.sqlite"
TAG = "SIC"
STATE = "STATE_ABRUZZO"
BUILDING = "building_furniture_manufactory"


class EditBuildingsTest(unittest.TestCase):
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
        self.conn.row_factory = sqlite3.Row
        self.added_ids: list[int] = []

    def tearDown(self) -> None:
        for bld_id in reversed(self.added_ids):
            self.conn.execute("DELETE FROM st_bld WHERE id = ?", (bld_id,))
        self.conn.commit()
        self.conn.close()

    def test_load_building_options(self) -> None:
        opts = load_building_options(self.conn, TAG, STATE, building=BUILDING)
        self.assertEqual(opts["tag"], TAG)
        self.assertIn(BUILDING, opts["buildings"])
        self.assertTrue(
            any(BUILDING in group["buildings"] for group in opts["building_groups"])
        )
        self.assertGreater(len(opts["pm_groups"]), 0)
        self.assertNotIn("building_machu_picchu", opts["buildings"])
        basic = [item["value"] for item in opts["ownership_types"][:4]]
        self.assertEqual(
            basic,
            ["financial_district", "manor_house", "self", "country"],
        )
        self.assertEqual(opts["defaults"]["ownership_type"], "country")
        furniture_group = next(
            group for group in opts["building_groups"] if BUILDING in group["buildings"]
        )
        self.assertEqual(furniture_group["building_group"], "bg_manufacturing")
        self.assertEqual(
            opts["building_group_map"][BUILDING], "bg_light_industry"
        )
        self.assertEqual(
            opts["building_group_map"]["building_eiffel_tower"], "bg_monuments"
        )
        government_group = next(
            group
            for group in opts["building_groups"]
            if group["building_group"] == "bg_government"
        )
        self.assertIn("building_eiffel_tower", government_group["buildings"])
        active_tags = {
            row[0]
            for row in self.conn.execute("SELECT DISTINCT tag FROM st_prov")
        }
        self.assertTrue(active_tags)
        self.assertTrue(set(opts["tags"]).issubset(active_tags))
        self.assertNotIn("ABK", opts["tags"])

    def test_owner_tag_must_be_active(self) -> None:
        with self.assertRaises(ValueError):
            add_building(
                self.conn,
                tag=TAG,
                state=STATE,
                building=BUILDING,
                pms=None,
                ownership_type="country",
                owner_tag="ABK",
            )

    def test_normalize_owner_tag_preserves_scope_semantics(self) -> None:
        empty = _normalize_ownership_for_scope(
            TAG, STATE, "financial_district", "", ""
        )
        self.assertEqual(empty.owner_tag, "")
        self.assertEqual(empty.owner_state, "")

        scope_tag = _normalize_ownership_for_scope(
            TAG, STATE, "financial_district", TAG, STATE
        )
        self.assertEqual(scope_tag.owner_tag, "")
        self.assertEqual(scope_tag.owner_state, "")

        other = _normalize_ownership_for_scope(
            TAG, STATE, "financial_district", "GBR", "STATE_ILE_DE_FRANCE"
        )
        self.assertEqual(other.owner_tag, "GBR")
        self.assertEqual(other.owner_state, "STATE_ILE_DE_FRANCE")

        self_own = _normalize_ownership_for_scope(
            TAG, STATE, "self", "GBR", "STATE_ILE_DE_FRANCE"
        )
        self.assertEqual(self_own.owner_tag, "")
        self.assertEqual(self_own.owner_state, "")

        country_own = _normalize_ownership_for_scope(
            TAG, STATE, "country", "", "STATE_ILE_DE_FRANCE"
        )
        self.assertEqual(country_own.owner_tag, "")
        self.assertEqual(country_own.owner_state, "")

    def test_parse_building_level_rejects_invalid_values(self) -> None:
        for raw in (0, -1, 2.5, "2.5", "abc", True):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError) as ctx:
                    parse_building_level(raw)
                self.assertEqual(str(ctx.exception), BUILDING_LEVEL_ERROR)

    def test_parse_building_level_accepts_positive_integer(self) -> None:
        self.assertEqual(parse_building_level(3), 3)
        self.assertEqual(parse_building_level("5"), 5)
        self.assertEqual(parse_building_level(4.0), 4)

    def test_add_building_rejects_invalid_level(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            add_building(
                self.conn,
                tag=TAG,
                state=STATE,
                building=BUILDING,
                pms=None,
                level=0,
            )
        self.assertEqual(str(ctx.exception), BUILDING_LEVEL_ERROR)

    def test_add_and_delete_building(self) -> None:
        result = add_building(
            self.conn,
            tag=TAG,
            state=STATE,
            building=BUILDING,
            pms=None,
            level=2,
            ownership_type="country",
        )
        self.conn.commit()
        bld_id = result["bld_id"]
        self.added_ids.append(bld_id)
        row = self.conn.execute(
            "SELECT level, owner_tag FROM st_bld_own WHERE bld_id = ?", (bld_id,)
        ).fetchone()
        self.assertEqual(int(row[0]), 2)
        self.assertEqual(row[1], "")
        delete_building(self.conn, tag=TAG, state=STATE, bld_id=bld_id)
        self.conn.commit()
        self.added_ids.remove(bld_id)
        gone = self.conn.execute(
            "SELECT 1 FROM st_bld WHERE id = ?", (bld_id,)
        ).fetchone()
        self.assertIsNone(gone)

    def test_update_syncs_pm_for_same_building_key(self) -> None:
        r1 = add_building(
            self.conn,
            tag=TAG,
            state=STATE,
            building=BUILDING,
            pms=None,
        )
        r2 = add_building(
            self.conn,
            tag=TAG,
            state=STATE,
            building=BUILDING,
            pms=None,
        )
        self.conn.commit()
        id1, id2 = r1["bld_id"], r2["bld_id"]
        self.added_ids.extend([id1, id2])

        opts = load_building_options(self.conn, TAG, STATE, building=BUILDING)
        alt_pm = opts["pm_groups"][0]["pms"][-1]

        update_building(
            self.conn,
            tag=TAG,
            state=STATE,
            bld_id=id1,
            pms=[alt_pm] * len(opts["first_pms"]),
            level=3,
            ownership_type="country",
            sync_pm_same_key=True,
        )
        self.conn.commit()

        pms1 = [
            row[0]
            for row in self.conn.execute(
                "SELECT pm FROM st_bld_pm WHERE bld_id = ? ORDER BY ord", (id1,)
            )
        ]
        pms2 = [
            row[0]
            for row in self.conn.execute(
                "SELECT pm FROM st_bld_pm WHERE bld_id = ? ORDER BY ord", (id2,)
            )
        ]
        self.assertEqual(pms1, pms2)
        self.assertEqual(pms1[0], alt_pm)


if __name__ == "__main__":
    unittest.main()
