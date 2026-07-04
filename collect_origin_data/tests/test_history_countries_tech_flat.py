from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from history_countries_tech_flat import (  # noqa: E402
    CountryTechRow,
    filter_by_ownership,
    parse_countries_paths,
    parse_countries_text,
)
from history_states_flat import StateOwnershipRow  # noqa: E402


TIER_4_SAMPLE = {
    "4": [
        "enclosure",
        "manufacturies",
        "steelworking",
        "law_enforcement",
    ]
}
ERA_1_SAMPLE = {
    "era_1": [
        "enclosure",
        "manufacturies",
        "urbanization",
    ]
}


class HistoryCountriesTechFlatTests(unittest.TestCase):
    def test_parse_tier_and_direct_tech(self) -> None:
        text = """
        COUNTRIES = {
            c:CHI ?= {
                effect_starting_technology_tier_4_tech = yes
                add_technology_researched = sericulture
            }
        }
        """
        rows = parse_countries_text(
            text,
            tier_expansions=TIER_4_SAMPLE,
            era_expansions=ERA_1_SAMPLE,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].tag, "CHI")
        self.assertEqual(rows[0].technologies[0], "enclosure")
        self.assertIn("sericulture", rows[0].technologies)
        self.assertIn("law_enforcement", rows[0].technologies)

    def test_parse_add_era_researched(self) -> None:
        text = """
        COUNTRIES = {
            c:GBR ?= {
                add_era_researched = era_1
                add_technology_researched = railways
            }
        }
        """
        rows = parse_countries_text(
            text,
            tier_expansions={},
            era_expansions=ERA_1_SAMPLE,
        )
        self.assertEqual(rows[0].technologies[:3], ["enclosure", "manufacturies", "urbanization"])
        self.assertEqual(rows[0].technologies[-1], "railways")

    def test_parse_unconditional_country_block(self) -> None:
        text = """
        COUNTRIES = {
            c:GBR = {
                effect_starting_technology_tier_1_tech = yes
                add_technology_researched = labor_movement
            }
        }
        """
        rows = parse_countries_text(
            text,
            tier_expansions={"1": ["railways", "dialectics"]},
            era_expansions={},
        )
        self.assertEqual(rows[0].tag, "GBR")
        self.assertEqual(rows[0].technologies[:2], ["railways", "dialectics"])
        self.assertEqual(rows[0].technologies[-1], "labor_movement")

    def test_mod_overrides_vanilla_for_same_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vanilla_dir = root / "vanilla"
            mod_dir = root / "mod"
            vanilla_dir.mkdir()
            mod_dir.mkdir()
            (vanilla_dir / "zzz_late.txt").write_text(
                'COUNTRIES = { c:CHI ?= { add_technology_researched = vanilla_tech } }',
                encoding="utf-8",
            )
            (mod_dir / "aaa_early.txt").write_text(
                'COUNTRIES = { c:CHI = { add_technology_researched = mod_tech } }',
                encoding="utf-8",
            )
            paths = [vanilla_dir / "zzz_late.txt", mod_dir / "aaa_early.txt"]
            rows = parse_countries_paths(
                paths,
                mod_dir=mod_dir,
                tier_expansions={},
                era_expansions={},
            )
            self.assertEqual(
                {row.tag: row.technologies for row in rows},
                {"CHI": ["mod_tech"]},
            )

    def test_later_tag_definition_wins_within_same_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_dir = root / "mod"
            mod_dir.mkdir()
            first = mod_dir / "aaa.txt"
            second = mod_dir / "bbb.txt"
            first.write_text(
                'COUNTRIES = { c:CHI ?= { add_technology_researched = old_tech } }',
                encoding="utf-8",
            )
            second.write_text(
                'COUNTRIES = { c:CHI ?= { add_technology_researched = new_tech } }',
                encoding="utf-8",
            )
            rows = parse_countries_paths(
                [first, second],
                mod_dir=mod_dir,
                tier_expansions={},
                era_expansions={},
            )
            self.assertEqual({row.tag: row.technologies for row in rows}, {"CHI": ["new_tech"]})

    def test_filter_by_ownership(self) -> None:
        rows = [
            CountryTechRow("CHI", ["urbanization"]),
            CountryTechRow("USA", ["railways"]),
        ]
        ownership = [
            StateOwnershipRow(state="STATE_A", tag="CHI"),
            StateOwnershipRow(state="STATE_B", tag="JAP"),
        ]
        filtered = filter_by_ownership(rows, ownership)
        self.assertEqual([row.tag for row in filtered], ["CHI", "JAP"])
        self.assertEqual(filtered[0].technologies, ["urbanization"])
        self.assertEqual(filtered[1].technologies, [])


if __name__ == "__main__":
    unittest.main()
