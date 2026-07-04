from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tempfile

from constants import RESOURCE_COLUMNS  # noqa: E402
from state_region_flat import parse_state_block, parse_state_regions_dir  # noqa: E402


class StateRegionResourceParseTests(unittest.TestCase):
    def test_hub_province_refs(self) -> None:
        block = """
        id = 64
        provinces = { x29CCD6 x486F6A x518021 x8001E0 x834B66 x9F4072 }
        city = x9F4072
        farm = "x518021"
        mine = x834B66
        wood = x486F6A
        arable_land = 77
        """
        row = parse_state_block("STATE_NORTH_RHINE", block)
        self.assertEqual(row.city, "x9F4072")
        self.assertEqual(row.farm, "x518021")
        self.assertEqual(row.mine, "x834B66")
        self.assertEqual(row.wood, "x486F6A")
        self.assertEqual(row.port, "")
        self.assertFalse(row.coastal)

    def test_unquoted_province_lists(self) -> None:
        block = """
        id = 64
        provinces = { x29CCD6 x486F6A x518021 }
        prime_land = { x518021 x486F6A }
        impassable = { x29CCD6 }
        arable_land = 77
        """
        row = parse_state_block("STATE_NORTH_RHINE", block)
        self.assertEqual(row.provinces, "x29CCD6,x486F6A,x518021")
        self.assertEqual(row.prime_land, "x518021,x486F6A")
        self.assertEqual(row.impassable, "x29CCD6")

    def test_undiscovered_resource_block(self) -> None:
        block = """
        id = 540
        provinces = { "x1" }
        arable_land = 10
        resource = {
            type = "building_rubber_plantation"
            undiscovered_amount = 40
        }
        """
        row = parse_state_block("STATE_MALAYA", block)
        self.assertEqual(row.resources["building_rubber_plantation"], 40)

    def test_discovered_resource_block(self) -> None:
        block = """
        id = 16
        provinces = { "x1" }
        arable_land = 10
        resource = {
            type = "building_oil_rig"
            discovered_amount = 20
        }
        """
        row = parse_state_block("STATE_LANCASHIRE", block)
        self.assertEqual(row.resources["building_oil_rig"], 20)

    def test_both_amounts_in_resource_block(self) -> None:
        block = """
        id = 542
        provinces = { "x1" }
        arable_land = 10
        resource = {
            type = "building_gold_field"
            depleted_type = "building_gold_mine"
            undiscovered_amount = 6
            discovered_amount = 4
        }
        """
        row = parse_state_block("STATE_WEST_BORNEO", block)
        self.assertEqual(row.resources["building_gold_field"], 10)

    def test_capped_and_resource_block_merge(self) -> None:
        block = """
        id = 540
        provinces = { "x1" }
        arable_land = 10
        capped_resources = {
            building_coal_mine = 32
            building_logging_camp = 17
        }
        resource = {
            type = "building_rubber_plantation"
            discovered_amount = 40
        }
        """
        row = parse_state_block("STATE_MALAYA", block)
        self.assertEqual(row.resources["building_coal_mine"], 32)
        self.assertEqual(row.resources["building_rubber_plantation"], 40)

    def test_commented_impassable_ignored(self) -> None:
        from vic3_assign import prepare_game_content

        block = """
        id = 189
        provinces = { "x1" "x2" "x3" "x4" "x5" }
        #impassable = { "x2" "x3" }
        traits = { "state_trait_atlas_mountains" }
        arable_land = 10
        """
        row = parse_state_block("STATE_TEST", prepare_game_content(block))
        self.assertEqual(row.impassable, "")

    def test_mod_state_overrides_vanilla_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vanilla_dir = root / "vanilla"
            mod_dir = root / "mod"
            vanilla_dir.mkdir()
            mod_dir.mkdir()
            (vanilla_dir / "aaa_vanilla.txt").write_text(
                """STATE_ALPHA = {
    id = 1
    provinces = { "x1" }
    arable_land = 10
}
STATE_BETA = {
    id = 2
    provinces = { "x2" }
    arable_land = 20
}
""",
                encoding="utf-8",
            )
            (mod_dir / "zzz_mod.txt").write_text(
                """STATE_ALPHA = {
    id = 1
    provinces = { "x1" "x9" }
    arable_land = 99
}
""",
                encoding="utf-8",
            )
            rows = parse_state_regions_dir(
                paths=[vanilla_dir / "aaa_vanilla.txt", mod_dir / "zzz_mod.txt"],
                mod_dir=mod_dir,
                resource_columns=RESOURCE_COLUMNS,
            )
            by_state = {row.state: row for row in rows}
            self.assertEqual(len(by_state), 2)
            self.assertEqual(by_state["STATE_ALPHA"].arable_land, 99)
            self.assertEqual(by_state["STATE_BETA"].arable_land, 20)

    def test_replace_or_create_state_region_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vanilla_dir = root / "vanilla"
            mod_dir = root / "mod"
            vanilla_dir.mkdir()
            mod_dir.mkdir()
            (vanilla_dir / "05_north_america.txt").write_text(
                """STATE_BERMUDA = {
    id = 321
    provinces = { "x169E2D" "xE55147" }
    arable_land = 10
}
""",
                encoding="utf-8",
            )
            (mod_dir / "zz_bermuda.txt").write_text(
                """REPLACE_OR_CREATE:STATE_BERMUDA = {
    id = 321
    provinces = { "x169E2D" "xE55147" }
    impassable = { "xE55147" }
    arable_land = 11
}
""",
                encoding="utf-8",
            )
            rows = parse_state_regions_dir(
                paths=[
                    vanilla_dir / "05_north_america.txt",
                    mod_dir / "zz_bermuda.txt",
                ],
                mod_dir=mod_dir,
                resource_columns=RESOURCE_COLUMNS,
            )
            by_state = {row.state: row for row in rows}
            self.assertIn("STATE_BERMUDA", by_state)
            self.assertEqual(by_state["STATE_BERMUDA"].arable_land, 11)
            self.assertEqual(by_state["STATE_BERMUDA"].impassable, "xE55147")

    def test_mod_malaya_file_snippet(self) -> None:
        mod = Path(
            "/home/liulingda/.steam/debian-installation/steamapps/workshop/content/529340/3346844497"
        )
        regions_dir = mod / "map_data/state_regions"
        if not regions_dir.is_dir():
            self.skipTest("未找到 Steam 工坊模组")
        rows = parse_state_regions_dir(regions_dir, resource_columns=RESOURCE_COLUMNS)
        row = next(r for r in rows if r.state == "STATE_MALAYA")
        self.assertEqual(row.resources["building_rubber_plantation"], 40)
        row = next(r for r in rows if r.state == "STATE_LANCASHIRE")
        self.assertEqual(row.resources["building_oil_rig"], 20)


if __name__ == "__main__":
    unittest.main()
