"""Tests for strategic region parsing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "map_db"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor_config import load_config  # noqa: E402
from parse_ref import parse_strategic_regions_paths  # noqa: E402


class ParseStrategicRegionsTest(unittest.TestCase):
    def test_states_are_parsed_from_brace_list(self) -> None:
        cfg = load_config()
        paths = tuple(sorted((cfg.vanilla / "common/strategic_regions").glob("*.txt")))
        rows = parse_strategic_regions_paths(paths)
        self.assertGreater(len(rows), 100)
        nile = next(row for row in rows if row.region == "region_nile_basin")
        self.assertIn("STATE_MIDDLE_EGYPT", nile.states)
        self.assertGreater(len(nile.states), 5)
        empty = [row.region for row in rows if not row.states]
        self.assertEqual(empty, [], msg=f"regions without states: {empty[:5]}")


if __name__ == "__main__":
    unittest.main()
