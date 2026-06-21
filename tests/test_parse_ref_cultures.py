"""Tests for culture / country definition parsing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parse_ref import (  # noqa: E402
    TagRow,
    _parse_brace_keys,
    parse_cultures_text,
)
from country_definitions_flat import (  # noqa: E402
    COUNTRY_HEADER_RE,
    _find_block_end,
    _parse_color,
)


class ParseRefCultureTest(unittest.TestCase):
    def test_parse_culture_rgb_color(self) -> None:
        text = """
north_german = {
    color = rgb { 62 77 100 }
    religion = protestant
}
"""
        rows = parse_cultures_text(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].culture, "north_german")
        self.assertEqual(rows[0].default_religion, "protestant")
        self.assertEqual((rows[0].r, rows[0].g, rows[0].b), (62, 77, 100))

    def test_parse_culture_hsv_color(self) -> None:
        text = """
british = {
    color = hsv { 0.99 0.7 0.9 }
    religion = protestant
}
"""
        rows = parse_cultures_text(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].culture, "british")
        self.assertGreater(rows[0].r, 0)
        self.assertGreater(rows[0].g, 0)
        self.assertGreater(rows[0].b, 0)

    def test_parse_country_cultures(self) -> None:
        text = """
GBR = {
    color = { 20 40 60 }
    country_type = recognized
    cultures = { british scottish }
    capital = STATE_HOME_COUNTIES
}
"""
        rows: list[TagRow] = []
        for match in COUNTRY_HEADER_RE.finditer(text):
            tag = match.group(1)
            block_start = match.end() - 1
            block_end = _find_block_end(text, block_start)
            block = text[block_start + 1 : block_end]
            rgb = _parse_color(block)
            self.assertIsNotNone(rgb)
            assert rgb is not None
            cultures = tuple(_parse_brace_keys(block, "cultures"))
            rows.append(
                TagRow(
                    tag=tag,
                    r=rgb[0],
                    g=rgb[1],
                    b=rgb[2],
                    cultures=cultures,
                )
            )

        self.assertEqual(rows[0].tag, "GBR")
        self.assertEqual(rows[0].cultures, ("british", "scottish"))


if __name__ == "__main__":
    unittest.main()
