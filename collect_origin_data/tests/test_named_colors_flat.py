from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from named_colors_flat import (  # noqa: E402
    build_named_color_lookup,
    parse_named_colors_paths,
    parse_named_colors_text,
)


class NamedColorsFlatTests(unittest.TestCase):
    def test_parse_hsv360_rgb_and_plain(self) -> None:
        text = """
colors = {
    red_dark = hsv360 { 1 95 35 }
    todo_purple = rgb { 1 0.4 0.6 }
    blue_steel = { 32 112 165 }
    roman_red = hsv { 0 0.91 0.55 }
}
"""
        rows = {row.key: row for row in parse_named_colors_text(text)}
        self.assertEqual((rows["red_dark"].r, rows["red_dark"].g, rows["red_dark"].b), (89, 6, 4))
        self.assertEqual((rows["todo_purple"].r, rows["todo_purple"].g, rows["todo_purple"].b), (255, 102, 153))
        self.assertEqual((rows["blue_steel"].r, rows["blue_steel"].g, rows["blue_steel"].b), (32, 112, 165))
        self.assertEqual((rows["roman_red"].r, rows["roman_red"].g, rows["roman_red"].b), (140, 13, 13))

    def test_mod_overrides_vanilla(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vanilla_dir = root / "vanilla"
            mod_dir = root / "mod"
            vanilla_dir.mkdir()
            mod_dir.mkdir()
            (vanilla_dir / "00.txt").write_text(
                'colors = { foo = rgb { 1 0 0 } }\n',
                encoding="utf-8",
            )
            (mod_dir / "00.txt").write_text(
                'colors = { foo = rgb { 0 1 0 } }\n',
                encoding="utf-8",
            )
            from game_content_resolver import merge_txt_paths

            paths, _source = merge_txt_paths(mod_dir, vanilla_dir)
            rows = parse_named_colors_paths(paths, mod_dir=mod_dir)
            lookup = build_named_color_lookup(rows)
            self.assertEqual(lookup["foo"], (0, 255, 0))


if __name__ == "__main__":
    unittest.main()
