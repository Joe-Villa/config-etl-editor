"""Tests for history export from map editor DB."""

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
    resolve_owner_state_for_export,
    resolve_owner_tag_for_export,
)
from interactive_map.export_history import (  # noqa: E402
    BuildingExportRow,
    OwnershipExportSlice,
    export_history_bundle,
    export_history_files,
    export_history_zip,
    load_buildings_for_export,
    load_history_files,
    load_pops_for_export,
    render_create_building,
    render_history_buildings,
    render_history_pops,
    render_history_states,
)

DB = ROOT / "output" / "test_map_editor.sqlite"
TAG = "SIC"
STATE = "STATE_ABRUZZO"
BUILDING = "building_furniture_manufactory"


class ExportHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "src"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def setUp(self) -> None:
        self.conn = sqlite3.connect(DB)
        self.added_ids: list[int] = []

    def tearDown(self) -> None:
        for bld_id in reversed(self.added_ids):
            self.conn.execute("DELETE FROM st_bld WHERE id = ?", (bld_id,))
        self.conn.commit()
        self.conn.close()

    def test_resolve_owner_fields_for_export(self) -> None:
        self.assertEqual(resolve_owner_tag_for_export(TAG, ""), TAG)
        self.assertEqual(resolve_owner_state_for_export(STATE, ""), STATE)
        self.assertEqual(resolve_owner_tag_for_export(TAG, "GBR"), "GBR")

    def test_export_writes_explicit_scope_owner_fields(self) -> None:
        result = add_building(
            self.conn,
            tag=TAG,
            state=STATE,
            building=BUILDING,
            pms=None,
            ownership_type="country",
            owner_tag="",
            owner_state="",
        )
        self.conn.commit()
        bld_id = result["bld_id"]
        self.added_ids.append(bld_id)

        stored = self.conn.execute(
            "SELECT owner_tag, owner_state FROM st_bld_own WHERE bld_id = ?",
            (bld_id,),
        ).fetchone()
        self.assertEqual(stored[0], "")
        self.assertEqual(stored[1], "")

        exported = next(
            row for row in load_buildings_for_export(self.conn) if row.bld_id == bld_id
        )
        self.assertEqual(exported.ownerships[0].owner_tag, TAG)
        self.assertEqual(exported.ownerships[0].owner_state, STATE)

        text = render_create_building(exported)
        self.assertIn('country = "c:SIC"', text)
        self.assertNotIn('country = ""', text)
        self.assertNotIn('country = "c:"', text)

    def test_export_keeps_explicit_non_scope_owner_state(self) -> None:
        row = BuildingExportRow(
            bld_id=0,
            state=STATE,
            tag=TAG,
            building=BUILDING,
            pms=(),
            ownerships=(
                OwnershipExportSlice(
                    ownership="financial_district",
                    level=2,
                    owner_tag=TAG,
                    owner_state="STATE_ILE_DE_FRANCE",
                ),
            ),
        )
        text = render_create_building(row)
        self.assertIn('country = "c:SIC"', text)
        self.assertIn('region = "STATE_ILE_DE_FRANCE"', text)
        self.assertNotIn('region = ""', text)

    def test_export_bundle_contains_three_history_files(self) -> None:
        conn = sqlite3.connect(DB)
        bundle = export_history_bundle(conn)
        file_map = export_history_files(conn)
        index = load_history_files(conn)
        conn.close()
        self.assertIn("BUILDINGS = {", bundle["buildings"])
        self.assertIn("POPS = {", bundle["pops"])
        self.assertIn("STATES = {", bundle["states"])
        self.assertIn("create_building", bundle["buildings"])
        self.assertIn("create_pop", bundle["pops"])
        self.assertIn("create_state", bundle["states"])
        self.assertGreater(len(file_map["buildings"]), 1)
        self.assertGreater(len(file_map["pops"]), 1)
        self.assertGreaterEqual(len(file_map["states"]), 1)
        self.assertIn("01_south_europe.txt", file_map["buildings"])
        self.assertEqual(len(file_map["buildings"]), len(index["buildings"]))
        self.assertEqual(len(file_map["pops"]), len(index["pops"]))
        self.assertEqual(len(file_map["states"]), len(index["states"]))

    def test_export_zip_has_folder_structure(self) -> None:
        import io
        import zipfile

        conn = sqlite3.connect(DB)
        file_map = export_history_files(conn)
        payload = export_history_zip(conn)
        index = load_history_files(conn)
        conn.close()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            self.assertTrue(any(name.startswith("history/buildings/") for name in names))
            self.assertTrue(any(name.startswith("history/pops/") for name in names))
            self.assertTrue(any(name.startswith("history/states/") for name in names))
            self.assertIn("history/buildings/01_south_europe.txt", names)
            for category in ("buildings", "pops", "states"):
                for filename in index[category]:
                    path = f"history/{category}/{filename}"
                    self.assertIn(path, names)
                    if index[category][filename]:
                        self.assertEqual(archive.read(path), b"")
                    else:
                        self.assertEqual(archive.read(path).decode("utf-8"), file_map[category][filename])

    def test_fallback_exports_empty_state_block(self) -> None:
        text = render_history_buildings(
            [],
            state_order=["STATE_ORPHAN"],
            include_empty_states=True,
        )
        self.assertIn("BUILDINGS = {", text)
        self.assertIn("\ts:STATE_ORPHAN = {", text)
        self.assertNotIn("create_building", text)

    def test_pop_export_omits_empty_religion(self) -> None:
        conn = sqlite3.connect(DB)
        rows = load_pops_for_export(conn)
        conn.close()
        self.assertGreater(len(rows), 0)
        row = next(r for r in rows if r.religion is None)
        text = render_history_pops([row])
        self.assertIn("culture =", text)
        self.assertNotIn("religion =", text)

    def test_state_export_includes_owned_provinces(self) -> None:
        conn = sqlite3.connect(DB)
        text = render_history_states(conn)
        conn.close()
        self.assertIn("owned_provinces = {", text)
        self.assertIn("x", text.lower())


if __name__ == "__main__":
    unittest.main()
