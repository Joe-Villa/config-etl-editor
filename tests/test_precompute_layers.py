"""Tests for precomputed static map layers in sqlite."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.db_reader import load_layer_png_bytes  # noqa: E402
from interactive_map.map_session import MapSession  # noqa: E402
from interactive_map.precompute_layers import (  # noqa: E402
    STATIC_LAYER_LABELS_ZH,
    STATIC_LAYER_NAMES,
    bake_static_layers,
    load_static_raster_context,
)

DB = ROOT / "output" / "test_map_editor.sqlite"


class PrecomputeLayersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "src"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def test_static_layers_stored_in_db(self) -> None:
        session = MapSession.open(DB)
        try:
            for layer in STATIC_LAYER_NAMES:
                stored = load_layer_png_bytes(session.conn, layer)
                self.assertIsNotNone(stored)
                self.assertGreater(len(stored), 1000)
                rendered = session.layer_png(layer)
                self.assertEqual(stored, rendered)
        finally:
            session.close()


    def test_static_layer_progress_callback(self) -> None:
        session = MapSession.open(DB)
        try:
            ctx = load_static_raster_context(session.conn)
            events: list[tuple[str, int, int]] = []

            def on_progress(label: str, done: int, total: int) -> None:
                events.append((label, done, total))

            bake_static_layers(ctx, session.conn, on_layer_progress=on_progress)
            self.assertEqual(len(STATIC_LAYER_NAMES), 5)
            self.assertEqual(events[0], (STATIC_LAYER_LABELS_ZH["terrain"], 0, 5))
            self.assertEqual(events[-1], (STATIC_LAYER_LABELS_ZH["border_province"], 5, 5))
            self.assertEqual(len(events), 6)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
