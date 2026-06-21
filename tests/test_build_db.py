"""Tests for map editor database builder."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_db import BuildMapDbError, build_map_db, _building_db_path, resolve_build_output_path  # noqa: E402
from editor_config import load_config  # noqa: E402
from parse_ref import parse_localization_merged  # noqa: E402


class BuildDbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config()
        cls.output = ROOT / "output" / "test_map_editor.sqlite"
        cls.log = build_map_db(
            cls.config.vanilla,
            cls.output,
            cls.config,
            fail_on_error=True,
        )

    def test_reference_counts(self) -> None:
        conn = sqlite3.connect(self.output)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM ref_tag").fetchone()[0], 100)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM ref_named_color").fetchone()[0], 50)
        self.assertGreater(
            conn.execute("SELECT COUNT(*) FROM ref_tag_culture").fetchone()[0], 100
        )
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM ref_bld").fetchone()[0], 50)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM ref_bg").fetchone()[0], 20)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM ref_sr_prime").fetchone()[0], 0)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM ref_sr_impassable").fetchone()[0], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM map_png").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM map_layer_png").fetchone()[0], 5)
        meta_keys = {
            row[0]
            for row in conn.execute(
                "SELECT key FROM meta WHERE key LIKE '%_count' OR key LIKE 'map_%' OR key = 'total_pixels'"
            )
        }
        self.assertIn("total_pixels", meta_keys)
        self.assertIn("prime_land_count", meta_keys)
        conn.close()

    def test_country_cultures_and_culture_colors(self) -> None:
        conn = sqlite3.connect(self.output)
        gbr = conn.execute(
            """
            SELECT culture, ord FROM ref_tag_culture
            WHERE tag = 'GBR'
            ORDER BY ord
            """
        ).fetchall()
        self.assertEqual([row[0] for row in gbr], ["british", "scottish"])

        british = conn.execute(
            "SELECT r, g, b FROM ref_culture WHERE culture = 'british'"
        ).fetchone()
        self.assertIsNotNone(british)
        self.assertGreater(int(british[0]), 0)
        self.assertGreater(int(british[1]), 0)
        self.assertGreater(int(british[2]), 0)

        from interactive_map.db_reader import (  # noqa: E402
            load_countries_json,
            load_cultures_json,
        )

        countries = load_countries_json(conn)
        self.assertEqual(countries["GBR"]["cultures"], ["british", "scottish"])
        self.assertEqual(countries["GBR"]["country_type"], "recognized")
        self.assertIn("british", load_cultures_json(conn))
        conn.close()

    def test_country_type_defaults_to_recognized(self) -> None:
        conn = sqlite3.connect(self.output)
        empty = conn.execute(
            "SELECT COUNT(*) FROM ref_tag WHERE country_type IS NULL OR country_type = ''"
        ).fetchone()[0]
        self.assertEqual(empty, 0)
        recognized = conn.execute(
            "SELECT COUNT(*) FROM ref_tag WHERE country_type = 'recognized'"
        ).fetchone()[0]
        self.assertGreater(recognized, 50)
        conn.close()

    def test_building_group_hierarchy_and_buildable(self) -> None:
        conn = sqlite3.connect(self.output)
        row = conn.execute(
            """
            SELECT bg.parent_group, bg.root_group, b.buildable
            FROM ref_bld b
            JOIN ref_bg bg ON b.building_group = bg.building_group
            WHERE b.building = 'building_furniture_manufactory'
            """
        ).fetchone()
        self.assertEqual(row[0], "bg_manufacturing")
        self.assertEqual(row[1], "bg_manufacturing")
        self.assertEqual(int(row[2]), 1)

        hidden = conn.execute(
            "SELECT buildable FROM ref_bld WHERE building = 'building_machu_picchu'"
        ).fetchone()
        self.assertIsNotNone(hidden)
        self.assertEqual(int(hidden[0]), 0)

        buildable_count = conn.execute(
            "SELECT COUNT(*) FROM ref_bld WHERE buildable = 1"
        ).fetchone()[0]
        total_count = conn.execute("SELECT COUNT(*) FROM ref_bld").fetchone()[0]
        self.assertLess(buildable_count, total_count)
        conn.close()

    def test_edit_counts(self) -> None:
        conn = sqlite3.connect(self.output)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM st").fetchone()[0], 500)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM st_pop").fetchone()[0], 1000)
        self.assertGreater(conn.execute("SELECT COUNT(*) FROM st_bld").fetchone()[0], 1000)
        conn.close()

    def test_slaves_pop_flag(self) -> None:
        conn = sqlite3.connect(self.output)
        n = conn.execute("SELECT COUNT(*) FROM st_pop WHERE is_slaves = 1").fetchone()[0]
        self.assertGreater(n, 0)
        conn.close()

    def test_religion_colors_and_names(self) -> None:
        conn = sqlite3.connect(self.output)
        catholic = conn.execute(
            """
            SELECT r, g, b, name_zh, name_en
            FROM ref_religion
            WHERE religion = 'catholic'
            """
        ).fetchone()
        self.assertIsNotNone(catholic)
        self.assertGreater(int(catholic[0]), 0)
        self.assertGreater(int(catholic[1]), 0)
        self.assertGreater(int(catholic[2]), 0)
        self.assertTrue(str(catholic[3]))
        self.assertTrue(str(catholic[4]))
        conn.close()

    def test_building_ownership_slices(self) -> None:
        conn = sqlite3.connect(self.output)
        total = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT b.id FROM st_bld b
                JOIN st_bld_own o ON o.bld_id = b.id
                GROUP BY b.id
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        self.assertGreater(total, 0)
        conn.close()

    def test_no_import_errors(self) -> None:
        self.assertTrue(self.log.ok)

    def test_localization_state_and_hub_names(self) -> None:
        conn = sqlite3.connect(self.output)
        row = conn.execute(
            "SELECT text FROM ref_loc WHERE loc_key = 'STATE_MINSK' AND locale = 'zh'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "明斯克")
        en_row = conn.execute(
            "SELECT text FROM ref_loc WHERE loc_key = 'STATE_MINSK' AND locale = 'en'"
        ).fetchone()
        self.assertIsNotNone(en_row)
        self.assertEqual(en_row[0], "Minsk")
        hub = conn.execute(
            "SELECT text FROM ref_loc WHERE loc_key = 'HUB_NAME_STATE_UUSIMAA_city' AND locale = 'zh'"
        ).fetchone()
        self.assertIsNotNone(hub)

        sys.path.insert(0, str(ROOT))
        from interactive_map.db_reader import load_names_json_all_locales  # noqa: E402

        names = load_names_json_all_locales(conn)
        self.assertEqual(names["zh"]["states"]["STATE_MINSK"], "明斯克")
        self.assertEqual(names["en"]["states"]["STATE_MINSK"], "Minsk")
        self.assertEqual(names["zh"]["hubs"]["STATE_UUSIMAA::city"], hub[0])
        self.assertEqual(names["zh"]["cultures"]["south_italian"], "南意大利")
        self.assertEqual(names["en"]["cultures"]["south_italian"], "South Italian")
        self.assertEqual(names["zh"]["religions"]["catholic"], "天主教")
        self.assertEqual(
            names["zh"]["buildings"]["building_furniture_manufactory"], "家具制造厂"
        )
        self.assertEqual(names["zh"]["pms"]["pm_handcrafted_furniture"], "手工家具")
        self.assertEqual(names["zh"]["companies"]["company_basic_food"], "优质食品")
        self.assertGreater(len(names["zh"]["building_groups"]), 30)
        self.assertEqual(names["zh"]["building_groups"]["bg_light_industry"], "轻工业")
        self.assertEqual(
            names["zh"]["country_types"]["recognized"], "受认可"
        )
        self.assertEqual(
            names["en"]["country_types"]["recognized"], "Recognized"
        )
        self.assertEqual(
            names["zh"]["pms"]["default_building_banana_plantation"], "$pm_default$"
        )
        conn.close()

    def test_localization_merges_mod_over_vanilla(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vanilla = root / "vanilla"
            mod = root / "mod"
            for game in (vanilla, mod):
                (game / "localization/simp_chinese").mkdir(parents=True)
            (vanilla / "localization/english").mkdir(parents=True)
            (vanilla / "localization/simp_chinese/cultures_l_simp_chinese.yml").write_text(
                'l_simp_chinese:\n south_italian: "南意大利"\n',
                encoding="utf-8",
            )
            (vanilla / "localization/english/cultures_l_english.yml").write_text(
                'l_english:\n south_italian: "South Italian"\n',
                encoding="utf-8",
            )
            (mod / "localization/simp_chinese/states_l_simp_chinese.yml").write_text(
                'l_simp_chinese:\n STATE_TEST: "模组州名"\n',
                encoding="utf-8",
            )
            rows = {
                row.key: row.text
                for row in parse_localization_merged(mod, vanilla, locale="zh")
            }
            self.assertEqual(rows["south_italian"], "南意大利")
            self.assertEqual(rows["STATE_TEST"], "模组州名")
            en_rows = {
                row.key: row.text
                for row in parse_localization_merged(mod, vanilla, locale="en")
            }
            self.assertEqual(en_rows["south_italian"], "South Italian")

    def test_supported_game_locales(self) -> None:
        from parse_ref import LOCALE_DIRS, SUPPORTED_LOCALES  # noqa: E402

        self.assertEqual(len(SUPPORTED_LOCALES), 11)
        self.assertEqual(set(SUPPORTED_LOCALES), set(LOCALE_DIRS))

    def test_all_locale_rows_in_ref_loc(self) -> None:
        from parse_ref import SUPPORTED_LOCALES  # noqa: E402

        conn = sqlite3.connect(self.output)
        for locale in SUPPORTED_LOCALES:
            count = conn.execute(
                "SELECT COUNT(*) FROM ref_loc WHERE locale = ?", (locale,)
            ).fetchone()[0]
            self.assertGreater(count, 0, f"ref_loc missing rows for locale {locale}")
        conn.close()


class MergeOwnershipRowsTest(unittest.TestCase):
    def test_unions_owned_provinces_for_duplicate_state_tag(self) -> None:
        from build_db import _merge_ownership_rows  # noqa: E402
        from history_states_flat import StateOwnershipRow  # noqa: E402
        from warn import ImportLog  # noqa: E402

        log = ImportLog()
        rows = [
            StateOwnershipRow(
                state="STATE_X",
                tag="AAA",
                owned_provinces=["x0001", "x0002"],
                state_type="incorporated",
            ),
            StateOwnershipRow(
                state="STATE_X",
                tag="AAA",
                owned_provinces=["x0002", "x0003"],
                state_type="unincorporated",
            ),
        ]
        merged = _merge_ownership_rows(rows, log)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].owned_provinces, ["x0001", "x0002", "x0003"])
        self.assertEqual(merged[0].state_type, "unincorporated")
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("重复 create_state", log.warnings[0])
        self.assertIn("1 个新 province", log.warnings[0])


class AtomicBuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config()

    def test_import_errors_leave_no_db_file(self) -> None:
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.sqlite"

            def _inject_error(_conn, _mod, _vanilla, log, _rp) -> None:
                log.error("synthetic import error")

            with patch("build_db._insert_ref_catalogs", _inject_error), patch(
                "build_db._insert_edit", lambda *_a, **_k: None
            ), patch("build_db._insert_map_assets", lambda *_a, **_k: None), patch(
                "build_db.insert_history_index", lambda *_a, **_k: None
            ):
                with self.assertRaises(BuildMapDbError) as ctx:
                    build_map_db(self.config.vanilla, out, self.config, fail_on_error=True)
                self.assertEqual(ctx.exception.log.errors, ["synthetic import error"])

            self.assertFalse(out.exists())
            self.assertFalse(_building_db_path(out).exists())

    def test_crash_during_build_leaves_no_db_file(self) -> None:
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.sqlite"

            def _boom(*_args, **_kwargs) -> None:
                raise ValueError("synthetic crash")

            with patch("build_db._insert_ref_catalogs", _boom):
                with self.assertRaises(ValueError):
                    build_map_db(self.config.vanilla, out, self.config, fail_on_error=True)

            self.assertFalse(out.exists())
            self.assertFalse(_building_db_path(out).exists())

    def test_map_assets_skipped_when_edit_has_errors(self) -> None:
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.sqlite"

            def _fail_edit(_conn, _mod, _vanilla, log, _rp) -> None:
                log.error("synthetic edit error")

            map_called = {"value": False}

            def _track_map(*_args, **_kwargs) -> None:
                map_called["value"] = True

            with patch("build_db._insert_edit", _fail_edit), patch(
                "build_db._insert_map_assets", _track_map
            ), patch("build_db.insert_history_index", lambda *_a, **_k: None):
                with self.assertRaises(BuildMapDbError):
                    build_map_db(self.config.vanilla, out, self.config, fail_on_error=True)

            self.assertFalse(map_called["value"])

    def test_successful_rebuild_replaces_old_db(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.sqlite"
            build_map_db(self.config.vanilla, out, self.config, fail_on_error=True)
            self.assertTrue(out.is_file())
            build_map_db(self.config.vanilla, out, self.config, fail_on_error=True)
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 0)
            self.assertFalse(_building_db_path(out).exists())

    def test_skip_map_images_writes_test_prefixed_db_without_map_png(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "out.sqlite"
            expected = resolve_build_output_path(base, skip_map_images=True)
            self.assertEqual(expected.name, "testout.sqlite")

            build_map_db(
                self.config.vanilla,
                base,
                self.config,
                fail_on_error=True,
                skip_map_images=True,
            )
            self.assertTrue(expected.is_file())
            self.assertFalse(base.exists())

            conn = sqlite3.connect(expected)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM map_png").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute(
                    "SELECT value FROM meta WHERE key = 'build_mode'"
                ).fetchone()[0],
                "test",
            )
            self.assertGreater(
                conn.execute("SELECT COUNT(*) FROM ref_tag").fetchone()[0], 100
            )
            conn.close()


if __name__ == "__main__":
    unittest.main()
