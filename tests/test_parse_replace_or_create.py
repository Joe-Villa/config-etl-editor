"""Tests for REPLACE_OR_CREATE definition headers in parse_ref."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parse_ref import (  # noqa: E402
    parse_company_types_text,
    parse_pm_groups_text,
    parse_religions_text,
    ReligionRow,
)


class ReplaceOrCreateParseTest(unittest.TestCase):
    def test_parse_pm_group_with_replace_or_create(self) -> None:
        text = """
REPLACE_OR_CREATE:pmg_base_gonglixuexiao = {
    production_methods = {
        pm_wusheshi
        pm_jichu_sheshi
    }
}
"""
        rows = parse_pm_groups_text(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].pm_group, "pmg_base_gonglixuexiao")
        self.assertEqual(rows[0].pms, ("pm_wusheshi", "pm_jichu_sheshi"))

    def test_parse_religion_with_replace_or_create(self) -> None:
        text = """
REPLACE_OR_CREATE:mayajiao = {
    heritage = heritage_meizhou
}
"""
        self.assertEqual(parse_religions_text(text), [
            ReligionRow(religion="mayajiao", r=255, g=255, b=255),
        ])

    def test_parse_company_with_replace_or_create(self) -> None:
        text = """
REPLACE_OR_CREATE:company_test_mod = {
    building = building_food_industry
}
"""
        self.assertEqual(parse_company_types_text(text), ["company_test_mod"])

    def test_jiuri_mod_pm_groups_file(self) -> None:
        mod_file = Path(
            "/home/liulingda/.steam/debian-installation/steamapps/workshop/content/529340/3260268786/common/production_method_groups/99__jiuri.txt"
        )
        if not mod_file.is_file():
            self.skipTest("jiuri mod 不在本机")
        rows = parse_pm_groups_text(mod_file.read_text(encoding="utf-8-sig"))
        groups = {row.pm_group for row in rows}
        self.assertIn("pmg_base_gonglixuexiao", groups)


if __name__ == "__main__":
    unittest.main()
