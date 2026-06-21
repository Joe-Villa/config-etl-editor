"""Tests for interactive map export from map editor DB."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "output" / "map_editor.sqlite"
WEB = ROOT / "interactive_map" / "output" / "view" / "web"


class ViewExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        need_build = not DB.is_file()
        if DB.is_file():
            conn = __import__("sqlite3").connect(DB)
            try:
                matched_states = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM ref_loc
                    WHERE locale = 'zh' AND loc_key IN (SELECT state FROM ref_sr)
                    """
                ).fetchone()[0]
            except __import__("sqlite3").OperationalError:
                matched_states = 0
            conn.close()
            need_build = matched_states == 0
        if need_build:
            subprocess.run(
                [sys.executable, str(ROOT / "run.py"), "--allow-errors"],
                check=True,
                cwd=ROOT,
            )
        subprocess.run(
            [sys.executable, str(ROOT / "view_map.py"), str(DB), "--export-only"],
            check=True,
            cwd=ROOT,
        )

    def test_web_assets_exist(self) -> None:
        required = [
            "provinces.png",
            "ownership.png",
            "country_type.png",
            "country_type.json",
            "provinces.json",
            "states.json",
            "countries.json",
            "names.json",
            "meta.json",
            "terrain.png",
            "incorporation.png",
            "homeland.png",
            "homeland.json",
            "foreign_investment.png",
            "hubs.png",
        ]
        for name in required:
            self.assertTrue((WEB / name).is_file(), name)

    def test_no_market_assets(self) -> None:
        self.assertFalse((WEB / "market.png").exists())
        self.assertFalse((WEB / "market_parent.json").exists())

    def test_names_only_from_db_entities(self) -> None:
        names = json.loads((WEB / "names.json").read_text(encoding="utf-8"))
        zh = names["zh"]
        conn = __import__("sqlite3").connect(DB)
        valid_tags = {r[0] for r in conn.execute("SELECT tag FROM ref_tag")}
        valid_states = {r[0] for r in conn.execute("SELECT state FROM ref_sr")}
        conn.close()
        self.assertTrue(set(zh["tags"]).issubset(valid_tags))
        self.assertTrue(set(zh["states"]).issubset(valid_states))
        self.assertNotIn("STATE_MARKET_CAPITAL_STATUS", zh["states"])
        conn = __import__("sqlite3").connect(DB)
        valid_cultures = {r[0] for r in conn.execute("SELECT culture FROM ref_culture")}
        valid_buildings = {r[0] for r in conn.execute("SELECT building FROM ref_bld")}
        conn.close()
        self.assertTrue(set(zh["cultures"]).issubset(valid_cultures))
        self.assertTrue(set(zh["buildings"]).issubset(valid_buildings))

    def test_names_include_states_and_hubs(self) -> None:
        names = json.loads((WEB / "names.json").read_text(encoding="utf-8"))
        zh = names["zh"]
        en = names["en"]
        self.assertGreater(len(zh["states"]), 100)
        self.assertGreater(len(zh["hubs"]), 100)
        self.assertEqual(zh["states"]["STATE_MINSK"], "明斯克")
        self.assertEqual(en["states"]["STATE_MINSK"], "Minsk")
        self.assertIn("STATE_UUSIMAA::city", zh["hubs"])

    def test_names_include_entity_localization(self) -> None:
        names = json.loads((WEB / "names.json").read_text(encoding="utf-8"))
        zh = names["zh"]
        self.assertGreater(len(zh["cultures"]), 100)
        self.assertGreater(len(zh["religions"]), 10)
        self.assertGreater(len(zh["buildings"]), 50)
        self.assertGreater(len(zh["pms"]), 100)
        self.assertGreater(len(zh["companies"]), 50)
        self.assertGreater(len(zh["building_groups"]), 30)
        self.assertEqual(zh["cultures"]["south_italian"], "南意大利")
        self.assertEqual(zh["buildings"]["building_furniture_manufactory"], "家具制造厂")
        self.assertEqual(zh["building_groups"]["bg_light_industry"], "轻工业")
        self.assertEqual(zh["companies"]["company_basic_food"], "优质食品")

    def test_states_have_population(self) -> None:
        states = json.loads((WEB / "states.json").read_text(encoding="utf-8"))
        sample = next(iter(states.values()))
        self.assertIn("population", sample)
        self.assertIn("state_type", sample)

    def test_meta_from_database_only(self) -> None:
        meta = json.loads((WEB / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["database"], DB.name)
        self.assertNotIn("mod_root", meta)
        self.assertNotIn("source_db", meta)

    def test_terrain_json_has_prime_and_impassable(self) -> None:
        terrain = json.loads((WEB / "terrain.json").read_text(encoding="utf-8"))
        self.assertGreater(len(terrain["prime_land"]), 0)
        self.assertGreater(len(terrain["impassable"]), 0)

    def test_sea_pixels_are_white_on_terrain_and_hubs(self) -> None:
        import numpy as np
        from PIL import Image

        import sqlite3

        from interactive_map.db_reader import load_provinces_png_bytes, load_sea_province_keys
        from interactive_map.png_util import province_rgb_keys_from_bytes

        conn = sqlite3.connect(DB)
        png = load_provinces_png_bytes(conn)
        rgb_keys, _ = province_rgb_keys_from_bytes(png)
        sea_keys = load_sea_province_keys(conn)
        conn.close()
        sea_mask = np.isin(rgb_keys, np.fromiter(sea_keys, dtype=np.uint32))

        for name in ("terrain.png", "hubs.png"):
            arr = np.array(Image.open(WEB / name).convert("RGB"))
            self.assertTrue(
                np.all(arr[sea_mask] == 255),
                f"{name} has non-white sea pixels",
            )


if __name__ == "__main__":
    unittest.main()
