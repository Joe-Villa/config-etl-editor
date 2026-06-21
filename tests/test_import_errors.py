"""Tests for strategic region map_color import errors."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from parse_ref import (  # noqa: E402
    parse_strategic_regions_text,
    scan_strategic_regions_file_map_color_errors,
)


class StrategicRegionMapColorTest(unittest.TestCase):
    def test_lexical_float_error_skipped_in_parse(self) -> None:
        text = (
            "region_bad = {\n"
            "    capital_province = x12345678\n"
            "    map_color = { 0.3 0.3 0.0.3 }\n"
            "    states = { STATE_A }\n"
            "}\n"
        )
        rows = parse_strategic_regions_text(text)
        self.assertEqual(rows, [])

    def test_scan_logs_location(self) -> None:
        text = (
            "region_bad = {\n"
            "    map_color = { 0.3 0.3 0.0.3 }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "strategic_regions" / "bad.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            log = type("L", (), {"error": lambda _s, m: errors.append(m)})()

            scan_strategic_regions_file_map_color_errors(path, mod_root, vanilla, log)
            self.assertEqual(len(errors), 1)
            self.assertIn("[mod]", errors[0])
            self.assertIn("bad.txt", errors[0])
            self.assertIn("0.0.3", errors[0])
            self.assertIn("region_bad", errors[0])


if __name__ == "__main__":
    unittest.main()
