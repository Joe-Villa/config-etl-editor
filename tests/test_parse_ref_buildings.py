"""Tests for building / building-group reference parsing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parse_ref import (  # noqa: E402
    parse_building_groups_text,
    parse_buildings_text,
    resolve_root_groups,
)


class ParseRefBuildingsTest(unittest.TestCase):
    def test_parse_building_group_parent(self) -> None:
        text = """
bg_manufacturing = { }
bg_light_industry = {
    parent_group = bg_manufacturing
}
"""
        rows = {r.building_group: r for r in parse_building_groups_text(text)}
        self.assertIsNone(rows["bg_manufacturing"].parent_group)
        self.assertEqual(rows["bg_light_industry"].parent_group, "bg_manufacturing")

    def test_resolve_root_group(self) -> None:
        text = """
bg_manufacturing = { }
bg_light_industry = { parent_group = bg_manufacturing }
bg_furniture = { parent_group = bg_light_industry }
"""
        rows = parse_building_groups_text(text)
        roots = resolve_root_groups(rows)
        self.assertEqual(roots["bg_manufacturing"], "bg_manufacturing")
        self.assertEqual(roots["bg_light_industry"], "bg_manufacturing")
        self.assertEqual(roots["bg_furniture"], "bg_manufacturing")

    def test_parse_buildable_flag(self) -> None:
        text = """
building_furniture_manufactory = {
    building_group = bg_light_industry
}
building_machu_picchu = {
    building_group = bg_monuments_hidden
    buildable = no
}
"""
        rows = {r.building: r for r in parse_buildings_text(text)}
        self.assertTrue(rows["building_furniture_manufactory"].buildable)
        self.assertFalse(rows["building_machu_picchu"].buildable)


if __name__ == "__main__":
    unittest.main()
