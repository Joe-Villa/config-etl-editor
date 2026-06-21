"""Tests for first PM per group (list order) during building import."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_db import normalize_site_pms, warn_duplicate_building_pm_mismatch  # noqa: E402
from parse_edit import BuildingSite  # noqa: E402
from pm_defaults import first_pm_for_group  # noqa: E402
from warn import ImportLog  # noqa: E402


class FirstPmTest(unittest.TestCase):
    def test_first_pm_is_list_head(self) -> None:
        pms = [
            "default_building_banana_plantation",
            "automatic_irrigation_building_banana_plantation",
        ]
        self.assertEqual(first_pm_for_group(pms), "default_building_banana_plantation")

    def test_first_pm_ignores_default_name_heuristic(self) -> None:
        pms = ["pm_simple_farming", "default_building_banana_plantation"]
        self.assertEqual(first_pm_for_group(pms), "pm_simple_farming")

    def test_first_pm_for_automation_group(self) -> None:
        pms = ["pm_automation_disabled", "pm_assembly_lines_building_arms_industry"]
        self.assertEqual(first_pm_for_group(pms), "pm_automation_disabled")

    def test_normalize_fills_missing_with_first_pm(self) -> None:
        pm_by_pmg = {
            "pmg_base_building_banana_plantation": [
                "default_building_banana_plantation",
                "automatic_irrigation_building_banana_plantation",
            ],
        }
        building_pmgs = {
            "building_banana_plantation": ["pmg_base_building_banana_plantation"],
        }
        site = BuildingSite(
            state="STATE_TEST",
            tag="TST",
            building="building_banana_plantation",
            pm=[],
            ownerships=[],
            reserves=1,
        )
        log = ImportLog()
        result = normalize_site_pms(site, pm_by_pmg, building_pmgs, log)
        self.assertEqual(result, ["default_building_banana_plantation"])
        self.assertEqual(log.errors, [])
        self.assertEqual(log.warnings, [])

    def test_normalize_missing_pm_group_is_silent(self) -> None:
        pm_by_pmg = {
            "pmg_base": ["pm_first", "pm_second"],
            "pmg_extra": ["pm_extra_default", "pm_extra_alt"],
        }
        building_pmgs = {"building_test": ["pmg_base", "pmg_extra"]}
        site = BuildingSite(
            state="STATE_TEST",
            tag="TST",
            building="building_test",
            pm=["pm_second"],
            ownerships=[],
            reserves=1,
        )
        log = ImportLog()
        result = normalize_site_pms(site, pm_by_pmg, building_pmgs, log)
        self.assertEqual(result, ["pm_second", "pm_extra_default"])
        self.assertEqual(log.errors, [])

    def test_normalize_extra_pm_group_warns(self) -> None:
        pm_by_pmg = {
            "pmg_base": ["pm_first"],
            "pmg_other": ["pm_other_only"],
        }
        building_pmgs = {
            "building_test": ["pmg_base"],
            "building_other": ["pmg_other"],
        }
        site = BuildingSite(
            state="STATE_TEST",
            tag="TST",
            building="building_test",
            pm=["pm_other_only"],
            ownerships=[],
            reserves=1,
        )
        log = ImportLog()
        result = normalize_site_pms(site, pm_by_pmg, building_pmgs, log)
        self.assertEqual(result, ["pm_first"])
        self.assertEqual(log.errors, [])
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("pm_other_only", log.warnings[0])
        self.assertIn("不属于本建筑的 PM 组", log.warnings[0])

    def test_normalize_unknown_pm_token_warns(self) -> None:
        pm_by_pmg = {"pmg_base": ["pm_first"]}
        building_pmgs = {"building_test": ["pmg_base"]}
        site = BuildingSite(
            state="STATE_TEST",
            tag="TST",
            building="building_test",
            pm=["pm_no_secondary"],
            ownerships=[],
            reserves=1,
        )
        log = ImportLog()
        result = normalize_site_pms(site, pm_by_pmg, building_pmgs, log)
        self.assertEqual(result, ["pm_first"])
        self.assertEqual(log.errors, [])
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("pm_no_secondary", log.warnings[0])
        self.assertIn("不在 PM 目录", log.warnings[0])
        pm_by_pmg = {
            "pmg_explosives_building_sulfur_mine": ["pm_no_explosives", "pm_dynamite"],
            "pmg_explosives_building_iron_mine": [
                "pm_no_explosives",
                "pm_dynamite_building_iron_mine",
            ],
        }
        building_pmgs = {
            "building_iron_mine": ["pmg_explosives_building_iron_mine"],
            "building_sulfur_mine": ["pmg_explosives_building_sulfur_mine"],
        }
        log = ImportLog()
        iron = BuildingSite(
            state="STATE_TEST",
            tag="TST",
            building="building_iron_mine",
            pm=["pm_dynamite_building_iron_mine"],
            ownerships=[],
            reserves=1,
        )
        sulfur = BuildingSite(
            state="STATE_TEST",
            tag="TST",
            building="building_sulfur_mine",
            pm=["pm_dynamite"],
            ownerships=[],
            reserves=1,
        )
        self.assertEqual(
            normalize_site_pms(iron, pm_by_pmg, building_pmgs, log),
            ["pm_dynamite_building_iron_mine"],
        )
        self.assertEqual(
            normalize_site_pms(sulfur, pm_by_pmg, building_pmgs, log),
            ["pm_dynamite"],
        )
        self.assertEqual(log.warnings, [])

    def test_normalize_shared_pm_name_resolves_by_building(self) -> None:
        pm_by_pmg = {
            "pmg_base_building_banana_plantation": [
                "default_building_banana_plantation",
                "automatic_irrigation_building_banana_plantation",
            ],
        }
        building_pmgs = {
            "building_banana_plantation": ["pmg_base_building_banana_plantation"],
        }
        site = BuildingSite(
            state="STATE_TEST",
            tag="TST",
            building="building_banana_plantation",
            pm=["automatic_irrigation_building_banana_plantation"],
            ownerships=[],
            reserves=1,
        )
        log = ImportLog()
        result = normalize_site_pms(site, pm_by_pmg, building_pmgs, log)
        self.assertEqual(result, ["automatic_irrigation_building_banana_plantation"])

    def test_warn_duplicate_building_pm_mismatch(self) -> None:
        log = ImportLog()
        seen: dict[tuple[str, str, str], list[str]] = {}
        site1 = BuildingSite(
            state="STATE_ANHALT",
            tag="PRU",
            building="building_rye_farm",
            pm=["pm_soil_enriching_farming", "pm_potatoes", "pm_tools"],
            ownerships=[],
            reserves=1,
        )
        site2 = BuildingSite(
            state="STATE_ANHALT",
            tag="PRU",
            building="building_rye_farm",
            pm=["pm_simple_farming", "pm_potatoes", "pm_tools_disabled"],
            ownerships=[],
            reserves=1,
        )
        warn_duplicate_building_pm_mismatch(
            site1, ["pm_soil_enriching_farming", "pm_potatoes", "pm_tools"], seen, log
        )
        warn_duplicate_building_pm_mismatch(
            site2, ["pm_simple_farming", "pm_potatoes", "pm_tools_disabled"], seen, log
        )
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("PM 不一致", log.warnings[0])
        self.assertIn("building_rye_farm", log.warnings[0])


if __name__ == "__main__":
    unittest.main()
