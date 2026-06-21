"""Tests for religion reference parsing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parse_ref import ReligionRow, parse_religions_text  # noqa: E402


class ParseReligionsTest(unittest.TestCase):
    def test_parse_religion_rgb_color(self) -> None:
        text = """
catholic = {
    icon = "gfx/interface/icons/religion_icons/catholic.dds"
    color = { 0.8 0.55 0.2 }
}
"""
        rows = parse_religions_text(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].religion, "catholic")
        self.assertEqual((rows[0].r, rows[0].g, rows[0].b), (204, 140, 51))

    def test_parse_religion_integer_color(self) -> None:
        text = """
protestant = {
    color = { 64 115 115 }
}
"""
        rows = parse_religions_text(text)
        self.assertEqual(rows[0], ReligionRow(religion="protestant", r=64, g=115, b=115))

    def test_parse_religion_without_color_defaults_white(self) -> None:
        text = """
animist = {
    heritage = heritage_pagan
}
"""
        rows = parse_religions_text(text)
        self.assertEqual(rows[0], ReligionRow(religion="animist", r=255, g=255, b=255))

    def test_nested_traits_not_parsed_as_religion(self) -> None:
        text = """
catholic = {
    texture = "gfx/interface/icons/religion_icons/catholic.dds"
    traits = {
        christian
    }
    color = { 0.8 0.6 0.4 }
}
"""
        warnings: list[str] = []
        rows = parse_religions_text(text, warnings=warnings)
        self.assertEqual([r.religion for r in rows], ["catholic"])
        self.assertEqual(warnings, ["宗教 catholic：过时的宗教写法"])

    def test_top_level_traits_block_skipped_with_warning(self) -> None:
        text = """
traits = {
    vtuber_world
}
"""
        warnings: list[str] = []
        rows = parse_religions_text(text, warnings=warnings)
        self.assertEqual(rows, [])
        self.assertEqual(warnings, ["宗教 traits：过时的宗教写法"])


if __name__ == "__main__":
    unittest.main()
