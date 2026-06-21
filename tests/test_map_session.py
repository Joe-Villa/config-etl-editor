"""Tests for runtime MapSession (SQL-driven, one-time PNG parse)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.map_session import MapSession  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


class MapSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "src"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def setUp(self) -> None:
        self.session = MapSession.open(DB)

    def tearDown(self) -> None:
        self.session.close()

    def test_png_parsed_once_and_json_from_sql(self) -> None:
        self.assertFalse(self.session.raster_parsed)
        self.assertEqual(self.session.width, 8192)
        self.assertEqual(self.session.height, 3616)
        self.session.refresh_view_layer("ownership")
        self.assertTrue(self.session.raster_parsed)
        keys_after = self.session._rgb_keys
        self.session.refresh_view_layer("ownership")
        self.assertIs(keys_after, self.session._rgb_keys)

    def test_layer_render_cached(self) -> None:
        self.session.refresh_view_layer("ownership")
        first = self.session.layer_png("ownership")
        second = self.session.layer_png("ownership")
        self.assertIs(first, second)
        self.assertGreater(len(first), 1000)

    def test_country_type_layer(self) -> None:
        png = self.session.layer_png("country_type")
        self.assertGreater(len(png), 1000)
        doc = self.session.json_document("country_type")
        self.assertIn("recognized", doc["vanilla_types"])
        self.assertIn("recognized", doc["tag_count_by_render_key"])
        self.assertNotIn("type_labels_zh", doc)
        countries = self.session.json_document("countries")
        self.assertIn("country_type", countries["GBR"])
        self.assertEqual(countries["GBR"]["country_type"], "recognized")

        names = self.session.json_document("names")
        self.assertEqual(names["zh"]["country_types"]["recognized"], "受认可")
        self.assertEqual(names["en"]["country_types"]["unrecognized"], "Unrecognized Country")

    def test_refresh_keeps_static_model_and_clears_dynamic_cache(self) -> None:
        self.session.refresh_view_layer("ownership")
        before = self.session.revision
        terrain_dict = self.session.model.terrain
        static_layer = self.session.layer_png("terrain")
        ownership = self.session.layer_png("ownership")
        foreign = self.session.layer_png("foreign_investment")
        slavery = self.session.layer_png("slavery")
        pop_total = self.session.layer_png("pop_total")
        rev = self.session.refresh()
        self.assertEqual(rev, before + 1)
        self.assertIs(terrain_dict, self.session.model.terrain)
        self.assertIs(static_layer, self.session.layer_png("terrain"))
        self.assertIsNot(ownership, self.session.layer_png("ownership"))
        self.assertIsNot(foreign, self.session.layer_png("foreign_investment"))
        self.assertIsNot(slavery, self.session.layer_png("slavery"))
        self.assertIsNot(pop_total, self.session.layer_png("pop_total"))

    def test_immutable_json_cached(self) -> None:
        first = self.session.json_document("names")
        second = self.session.json_document("names")
        self.assertIs(first, second)

    def test_meta_has_revision(self) -> None:
        meta = self.session.meta_json()
        self.assertEqual(meta["revision"], self.session.revision)
        self.assertEqual(meta["database"], DB.name)


if __name__ == "__main__":
    unittest.main()
