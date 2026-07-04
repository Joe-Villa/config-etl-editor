from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from country_definitions_flat import (  # noqa: E402
    CountryDefinitionRow,
    parse_country_definitions_text,
    scan_country_definitions_file_errors,
    validate_active_tags_have_definitions,
)


class CountryDefinitionsFlatTests(unittest.TestCase):
    def test_parse_rgb_and_hsv_formats(self) -> None:
        text = """
GER = {
    color = { 147 130 110 }
}
GBR = {
    color = hsv{ 0.99  0.7  0.9 }
}
SPA = {
    color = hsv360{ 20  80  80 }
}
DEC = {
    color = rgb { 190 160 240 }
}
"""
        rows = {row.tag: row for row in parse_country_definitions_text(text)}
        self.assertEqual((rows["GER"].r, rows["GER"].g, rows["GER"].b), (147, 130, 110))
        self.assertEqual((rows["GBR"].r, rows["GBR"].g, rows["GBR"].b), (230, 69, 78))
        self.assertEqual((rows["SPA"].r, rows["SPA"].g, rows["SPA"].b), (204, 95, 41))
        self.assertEqual((rows["DEC"].r, rows["DEC"].g, rows["DEC"].b), (190, 160, 240))

    def test_parse_replace_or_create_prefix(self) -> None:
        text = """
REPLACE_OR_CREATE:YUE = {
    color = { 96 173 250 }
}
"""
        rows = parse_country_definitions_text(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].tag, "YUE")
        self.assertEqual((rows[0].r, rows[0].g, rows[0].b), (96, 173, 250))

    def test_parse_variable_length_tags(self) -> None:
        text = """
RITA = {
    color = { 73 152 76 }
}
USAF = {
    color = { 190 186 202 }
}
YUZ1 = {
    color = hsv{ 0.99 0.7 0.9 }
}
"""
        rows = {row.tag: row for row in parse_country_definitions_text(text)}
        self.assertEqual((rows["RITA"].r, rows["RITA"].g, rows["RITA"].b), (73, 152, 76))
        self.assertEqual((rows["USAF"].r, rows["USAF"].g, rows["USAF"].b), (190, 186, 202))
        self.assertEqual(rows["YUZ1"].tag, "YUZ1")

    def test_parse_permissive_line_start_tag(self) -> None:
        text = """
MY-MOD_TAG = {
    color = { 10 20 30 }
}
"""
        rows = {row.tag: row for row in parse_country_definitions_text(text)}
        self.assertEqual(rows["MY-MOD_TAG"].tag, "MY-MOD_TAG")
        self.assertEqual((rows["MY-MOD_TAG"].r, rows["MY-MOD_TAG"].g, rows["MY-MOD_TAG"].b), (10, 20, 30))

    def test_hsv360_without_space_before_brace(self) -> None:
        text = """
STLI = {
    color = hsv360{ 357 90 87 }
}
"""
        rows = {row.tag: row for row in parse_country_definitions_text(text)}
        self.assertEqual(rows["STLI"].tag, "STLI")
        self.assertGreater(rows["STLI"].r, 0)

    def test_skip_commented_and_indented_headers(self) -> None:
        text = """
#USA = {
#    color = { 1 2 3 }
#}
USA = {
    color = { 4 5 6 }
    nested_block = {
        foo = yes
    }
}
"""
        rows = {row.tag: row for row in parse_country_definitions_text(text)}
        self.assertEqual(set(rows), {"USA"})
        self.assertEqual((rows["USA"].r, rows["USA"].g, rows["USA"].b), (4, 5, 6))

    def test_skip_dynamic_definition_without_color(self) -> None:
        text = """
D00 = {
    dynamic_country_definition = yes
}
"""
        rows = parse_country_definitions_text(text)
        self.assertEqual(rows, [])

    def test_scan_dynamic_definition_without_color_no_error(self) -> None:
        text = """
D00 = {
    dynamic_country_definition = yes
}
"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "country_definitions" / "00.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            log = type("L", (), {"error": lambda _s, m: errors.append(m)})()
            scan_country_definitions_file_errors(path, mod_root, vanilla, log)
            self.assertEqual(errors, [])

    def test_parse_missing_color_uses_default_rgb(self) -> None:
        text = """
BAD = {
    country_type = recognized
}
"""
        warnings: list[str] = []
        rows = {row.tag: row for row in parse_country_definitions_text(text, warnings=warnings)}
        self.assertEqual((rows["BAD"].r, rows["BAD"].g, rows["BAD"].b), (230, 230, 230))
        self.assertEqual(len(warnings), 1)
        self.assertIn("缺少 color", warnings[0])
        self.assertIn("230, 230, 230", warnings[0])

    def test_scan_missing_color_logs_warning(self) -> None:
        text = """
BAD = {
    country_type = recognized
}
"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "country_definitions" / "00.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            warnings: list[str] = []
            log = type(
                "L",
                (),
                {
                    "error": lambda _s, m: errors.append(m),
                    "warn": lambda _s, m: warnings.append(m),
                },
            )()
            scan_country_definitions_file_errors(path, mod_root, vanilla, log)
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)
            self.assertIn("BAD", warnings[0])
            self.assertIn("缺少 color", warnings[0])
            self.assertIn("230, 230, 230", warnings[0])

    def test_parse_rgba_four_components_uses_rgb(self) -> None:
        text = """
RKM = {
    color = { 35 45 44 255 }
}
"""
        rows = {row.tag: row for row in parse_country_definitions_text(text)}
        self.assertEqual((rows["RKM"].r, rows["RKM"].g, rows["RKM"].b), (35, 45, 44))

    def test_scan_rgba_four_components_no_error(self) -> None:
        text = """
RKM = {
    color = { 35 45 44 255 }
}
"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "country_definitions" / "00.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            warnings: list[str] = []
            log = type(
                "L",
                (),
                {
                    "error": lambda _s, m: errors.append(m),
                    "warn": lambda _s, m: warnings.append(m),
                },
            )()
            scan_country_definitions_file_errors(path, mod_root, vanilla, log)
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)
            self.assertIn("RKM", warnings[0])
            self.assertIn("非官方写法", warnings[0])
            self.assertIn("RGBA", warnings[0])

    def test_scan_official_rgb_no_warning(self) -> None:
        text = """
GER = {
    color = { 147 130 110 }
}
"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "country_definitions" / "00.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            warnings: list[str] = []
            log = type(
                "L",
                (),
                {
                    "error": lambda _s, m: None,
                    "warn": lambda _s, m: warnings.append(m),
                },
            )()
            scan_country_definitions_file_errors(path, mod_root, vanilla, log)
            self.assertEqual(warnings, [])

    def test_parse_text_warns_on_unquoted_named_color(self) -> None:
        text = """
MANE = {
    color = red_china
}
"""
        warnings: list[str] = []
        lookup = {"red_china": (223, 27, 18)}
        rows = parse_country_definitions_text(
            text,
            named_colors=lookup,
            warnings=warnings,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(warnings), 1)
        self.assertIn("MANE", warnings[0])
        self.assertIn("非官方写法", warnings[0])

    def test_scan_brace_swallow_logs_error(self) -> None:
        text = """
GER = {
    color = { 1 2 3 }
FRA = {
    color = { 4 5 6 }
}
}
"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "country_definitions" / "00.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            log = type("L", (), {"error": lambda _s, m: errors.append(m)})()
            scan_country_definitions_file_errors(path, mod_root, vanilla, log)
            self.assertEqual(len(errors), 1)
            self.assertIn("GER", errors[0])
            self.assertIn("FRA", errors[0])

    def test_mod_overrides_vanilla(self) -> None:
        from game_content_resolver import merge_txt_paths

        with self.subTest("file merge"):
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                vanilla_dir = root / "vanilla"
                mod_dir = root / "mod"
                vanilla_dir.mkdir()
                mod_dir.mkdir()
                (vanilla_dir / "00.txt").write_text(
                    "AAA = { color = { 1 2 3 } }\n",
                    encoding="utf-8",
                )
                (mod_dir / "00.txt").write_text(
                    "AAA = { color = { 9 8 7 } }\n",
                    encoding="utf-8",
                )
                paths, source = merge_txt_paths(mod_dir, vanilla_dir)
                from country_definitions_flat import parse_country_definitions_paths

                rows = parse_country_definitions_paths(paths, mod_dir=mod_dir)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0], CountryDefinitionRow(tag="AAA", r=9, g=8, b=7))

    def test_validate_active_tags(self) -> None:
        definitions = [CountryDefinitionRow(tag="GER", r=1, g=2, b=3)]
        validate_active_tags_have_definitions({"GER"}, definitions)
        with self.assertRaisesRegex(ValueError, "FRA"):
            validate_active_tags_have_definitions({"GER", "FRA"}, definitions)

    def test_parse_named_color_reference(self) -> None:
        text = """
SOV = {
    color = "red_dark"
}
"""
        lookup = {"red_dark": (89, 6, 4)}
        rows = {row.tag: row for row in parse_country_definitions_text(text, named_colors=lookup)}
        self.assertEqual(rows["SOV"].tag, "SOV")
        self.assertEqual((rows["SOV"].r, rows["SOV"].g, rows["SOV"].b), (89, 6, 4))

    def test_parse_unquoted_named_color_reference(self) -> None:
        text = """
MANE = {
    color = red_china
}
"""
        lookup = {"red_china": (223, 27, 18)}
        rows = {row.tag: row for row in parse_country_definitions_text(text, named_colors=lookup)}
        self.assertEqual((rows["MANE"].r, rows["MANE"].g, rows["MANE"].b), (223, 27, 18))

    def test_scan_unknown_named_color_logs_warning(self) -> None:
        text = """
BAD = {
    color = "missing_color"
}
"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "country_definitions" / "00.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            warnings: list[str] = []
            log = type(
                "L",
                (),
                {
                    "error": lambda _s, m: errors.append(m),
                    "warn": lambda _s, m: warnings.append(m),
                },
            )()
            scan_country_definitions_file_errors(
                path,
                mod_root,
                vanilla,
                log,
                named_colors={"red_dark": (1, 2, 3)},
            )
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)
            self.assertIn("missing_color", warnings[0])
            self.assertIn("230, 230, 230", warnings[0])

    def test_scan_unknown_unquoted_named_color_logs_warning(self) -> None:
        text = """
BAD = {
    color = red_china
}
"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "country_definitions" / "00.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            warnings: list[str] = []
            log = type(
                "L",
                (),
                {
                    "error": lambda _s, m: errors.append(m),
                    "warn": lambda _s, m: warnings.append(m),
                },
            )()
            scan_country_definitions_file_errors(
                path,
                mod_root,
                vanilla,
                log,
                named_colors={"red_dark": (1, 2, 3)},
            )
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)
            self.assertIn("red_china", warnings[0])
            self.assertIn("230, 230, 230", warnings[0])


if __name__ == "__main__":
    unittest.main()
