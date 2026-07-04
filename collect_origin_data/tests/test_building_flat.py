from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from building_flat import _parse_create_building_block, merge_building_rows, FlatBuilding  # noqa: E402


class BuildingKeyParseTests(unittest.TestCase):
    def test_vanilla_building_key(self) -> None:
        block = """
            building = "building_logging_camp"
            level = 1
            reserves = 1
        """
        row = _parse_create_building_block(block, "STATE_A", "CHI")
        self.assertEqual(row.name, "building_logging_camp")

    def test_mod_building_key_without_building_prefix(self) -> None:
        block = """
            building = "new_small_town"
            level = 1
            reserves = 1
        """
        row = _parse_create_building_block(block, "STATE_A", "CHI")
        self.assertEqual(row.name, "new_small_town")

    def test_unquoted_building_key(self) -> None:
        block = """
            building = building_construction_sector
            add_ownership = {
                country = {
                    country = c:AFG
                    levels = 5
                }
            }
            reserves = 1
        """
        row = _parse_create_building_block(block, "STATE_A", "AFG")
        self.assertEqual(row.name, "building_construction_sector")
        self.assertEqual(row.level, 5)

        block = """
            building="building_port"
            level = 2
        """
        row = _parse_create_building_block(block, "STATE_B", "USA")
        self.assertEqual(row.name, "building_port")

    def test_building_owner_region_before_levels(self) -> None:
        block = """
            building = "building_shipyard"
            reserves = 1
            add_ownership = {
                building = {
                    type = "building_shipyard"
                    country = "c:GOT"
                    region = "STATE_GOTLAND"
                    levels = 1
                }
            }
        """
        row = _parse_create_building_block(block, "STATE_GOTLAND", "GOT")
        self.assertEqual(row.ownership, "self")
        self.assertEqual(row.level, 1)

    def test_skip_non_unit_reserves(self) -> None:
        block = """
            building = "building_port"
            reserves = 2
            add_ownership = {
                country = {
                    country = "c:GOT"
                    levels = 1
                }
            }
        """
        row = _parse_create_building_block(block, "STATE_GOTLAND", "GOT")
        self.assertIsNone(row)

    def test_building_owner_levels_before_region(self) -> None:
        block = """
            building="building_rye_farm"
            add_ownership={
                building={
                    type="building_rye_farm"
                    country="c:DEN"
                    levels=8
                    region="STATE_JUTLAND"
                }
            }
            reserves=1
        """
        row = _parse_create_building_block(block, "STATE_JUTLAND", "DEN")
        self.assertEqual(row.ownership, "self")
        self.assertEqual(row.level, 8)


class BuildingMergeTests(unittest.TestCase):
    def _row(
        self,
        *,
        ownership: str = "country",
        owner_tag: str = "",
        owner_state: str = "",
        level: int = 1,
        pm: list[str] | None = None,
    ) -> FlatBuilding:
        return FlatBuilding(
            country="CHI",
            state="STATE_BEIJING",
            name="building_textile_mill",
            level=level,
            pm=pm or ["pm_default"],
            ownership=ownership,
            owner_tag=owner_tag,
            owner_state=owner_state,
        )

    def test_merge_same_ownership_and_pm_sums_levels(self) -> None:
        rows = merge_building_rows([self._row(level=3), self._row(level=2)])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].level, 5)

    def test_split_ownership_keeps_separate_rows(self) -> None:
        rows = merge_building_rows(
            [
                self._row(ownership="country", level=4),
                self._row(
                    ownership="manor_house",
                    owner_tag="GBR",
                    owner_state="STATE_HOME_COUNTIES",
                    level=2,
                ),
            ]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            sorted(row.level for row in rows),
            [2, 4],
        )

    def test_pm_mismatch_skips_conflicting_row(self) -> None:
        warnings: list[str] = []
        rows = merge_building_rows(
            [
                self._row(level=1, pm=["pm_a"]),
                self._row(level=2, pm=["pm_b"]),
            ],
            on_warn=warnings.append,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].level, 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("PM 不一致", warnings[0])

    def test_pm_order_difference_is_silent(self) -> None:
        warnings: list[str] = []
        rows = merge_building_rows(
            [
                self._row(level=1, pm=["pm_a", "pm_b"]),
                self._row(level=2, pm=["pm_b", "pm_a"]),
            ],
            on_warn=warnings.append,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].level, 3)
        self.assertEqual(warnings, [])

    def test_split_ownership_with_same_pm_is_allowed(self) -> None:
        pm = ["pm_a", "pm_b"]
        rows = merge_building_rows(
            [
                self._row(ownership="country", level=1, pm=pm),
                self._row(
                    ownership="manor_house",
                    owner_tag="GBR",
                    level=3,
                    pm=list(pm),
                ),
            ]
        )
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.pm == pm for row in rows))


if __name__ == "__main__":
    unittest.main()
