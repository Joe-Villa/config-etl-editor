"""Tests for province PNG helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.map_session import load_provinces_png_bytes, png_size  # noqa: E402
from interactive_map.png_util import province_rgb_keys_from_bytes  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


class PngUtilTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            raise unittest.SkipTest(f"missing test db: {DB}")

    def test_province_rgb_keys_map_size_matches_png_size(self) -> None:
        import sqlite3

        conn = sqlite3.connect(DB)
        try:
            png = load_provinces_png_bytes(conn)
        finally:
            conn.close()
        _, map_size = province_rgb_keys_from_bytes(png)
        self.assertEqual(map_size, png_size(png))


if __name__ == "__main__":
    unittest.main()
