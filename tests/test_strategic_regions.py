"""Tests for strategic region map layer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.strategic_regions import (  # noqa: E402
    load_province_strategic_region,
    normalize_map_color_component,
    render_strategic_region_png,
)
from interactive_map.map_session import MapSession  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


class StrategicRegionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "src"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def test_normalize_map_color_component(self) -> None:
        self.assertEqual(normalize_map_color_component(0.5), 128)
        self.assertEqual(normalize_map_color_component(72.0), 72)

    def test_strategic_region_layer_non_empty(self) -> None:
        session = MapSession.open(DB)
        try:
            labels = load_province_strategic_region(session.conn)
            self.assertGreater(len(labels), 1000)
            png = session.layer_png("strategic_region")
            self.assertGreater(len(png), 1000)
            runtime = render_strategic_region_png(session.model, session.conn)
            self.assertEqual(png, runtime)
        finally:
            session.close()

    def test_strategic_regions_json_document(self) -> None:
        session = MapSession.open(DB)
        try:
            payload = session.json_document("strategic_regions")
            self.assertIn("regions", payload)
            self.assertIn("state_region", payload)
            self.assertIn("province_state", payload)
            self.assertGreater(len(payload["regions"]), 10)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
