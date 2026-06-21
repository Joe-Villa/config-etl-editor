"""Tests for ref_hist_src indexing at database build."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from editor_config import load_config  # noqa: E402
from history_source_index import (  # noqa: E402
    FALLBACK_BASE,
    _effective_history_paths,
    build_history_file_rows,
    build_history_source_rows,
    scan_history_state_sources,
    unique_fallback_name,
)

DB = ROOT / "output" / "test_map_editor.sqlite"


class HistorySourceIndexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            from build_db import build_map_db  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def test_unique_fallback_name_appends_a(self) -> None:
        existing = {FALLBACK_BASE, "_fallbacka.txt"}
        self.assertEqual(unique_fallback_name(existing), "_fallbackaa.txt")

    def test_ref_hist_src_covers_all_states(self) -> None:
        conn = sqlite3.connect(DB)
        try:
            sr_count = conn.execute("SELECT COUNT(*) FROM ref_sr").fetchone()[0]
            src_count = conn.execute("SELECT COUNT(*) FROM ref_hist_src").fetchone()[0]
            self.assertEqual(src_count, sr_count)
        finally:
            conn.close()

    def test_ref_hist_file_lists_all_effective_filenames(self) -> None:
        conn = sqlite3.connect(DB)
        try:
            for category in ("buildings", "pops", "states"):
                count = conn.execute(
                    "SELECT COUNT(*) FROM ref_hist_file WHERE category = ?",
                    (category,),
                ).fetchone()[0]
                self.assertGreater(count, 0)
            fb = conn.execute(
                "SELECT COUNT(*) FROM ref_hist_file WHERE filename LIKE '_fallback%.txt'"
            ).fetchone()[0]
            self.assertEqual(fb, 0)
        finally:
            conn.close()

    def test_known_state_maps_to_vanilla_buildings_file(self) -> None:
        conn = sqlite3.connect(DB)
        try:
            row = conn.execute(
                """
                SELECT bld_file, pop_file, st_file
                FROM ref_hist_src
                WHERE state = 'STATE_ABRUZZO'
                """
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "01_south_europe.txt")
            self.assertEqual(row[1], "01_south_europe.txt")
            self.assertEqual(row[2], "00_states.txt")
        finally:
            conn.close()

    def test_mod_source_file_overrides_vanilla_for_same_state(self) -> None:
        vanilla = ROOT / "tmp_hist_src_vanilla" / "common" / "history" / "buildings"
        mod = ROOT / "tmp_hist_src_mod" / "common" / "history" / "buildings"
        vanilla.mkdir(parents=True, exist_ok=True)
        mod.mkdir(parents=True, exist_ok=True)
        try:
            (vanilla / "05_north_america.txt").write_text(
                "BUILDINGS = {\n"
                "\ts:STATE_TEST = {\n"
                "\t\tregion_state:USA = {\n"
                "\t\t}\n"
                "\t}\n"
                "\ts:STATE_VANILLA_ONLY = {\n"
                "\t\tregion_state:USA = {\n"
                "\t\t}\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            (mod / "01_custom.txt").write_text(
                "BUILDINGS = {\n"
                "\ts:STATE_TEST = {\n"
                "\t\tregion_state:USA = {\n"
                "\t\t}\n"
                "\t}\n"
                "\ts:STATE_MOD_ONLY = {\n"
                "\t\tregion_state:USA = {\n"
                "\t\t}\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            mapping = scan_history_state_sources(
                (vanilla / "05_north_america.txt", mod / "01_custom.txt")
            )
            self.assertEqual(mapping["STATE_TEST"].file, "01_custom.txt")
            self.assertEqual(mapping["STATE_MOD_ONLY"].file, "01_custom.txt")
            self.assertEqual(mapping["STATE_VANILLA_ONLY"].file, "05_north_america.txt")
        finally:
            import shutil

            shutil.rmtree(ROOT / "tmp_hist_src_vanilla", ignore_errors=True)
            shutil.rmtree(ROOT / "tmp_hist_src_mod", ignore_errors=True)

    def test_same_filename_reads_mod_file_only(self) -> None:
        vanilla = ROOT / "tmp_hist_src_vanilla" / "common" / "history" / "buildings"
        mod = ROOT / "tmp_hist_src_mod" / "common" / "history" / "buildings"
        vanilla.mkdir(parents=True, exist_ok=True)
        mod.mkdir(parents=True, exist_ok=True)
        try:
            shared = "01_south_europe.txt"
            (vanilla / shared).write_text(
                "BUILDINGS = {\n"
                "\ts:STATE_IN_VANILLA_ONLY = {\n"
                "\t\tregion_state:USA = {\n"
                "\t\t}\n"
                "\t}\n"
                "\ts:STATE_IN_BOTH = {\n"
                "\t\tregion_state:USA = {\n"
                "\t\t}\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            (mod / shared).write_text(
                "BUILDINGS = {\n"
                "\ts:STATE_IN_BOTH = {\n"
                "\t\tregion_state:USA = {\n"
                "\t\t}\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            mapping = scan_history_state_sources((mod / shared,))
            self.assertEqual(mapping["STATE_IN_BOTH"].file, shared)
            self.assertNotIn("STATE_IN_VANILLA_ONLY", mapping)
        finally:
            import shutil

            shutil.rmtree(ROOT / "tmp_hist_src_vanilla", ignore_errors=True)
            shutil.rmtree(ROOT / "tmp_hist_src_mod", ignore_errors=True)

    def test_effective_paths_use_mod_when_filename_collides(self) -> None:
        mod_root = ROOT / "tmp_hist_src_mod"
        vanilla_root = ROOT / "tmp_hist_src_vanilla"
        rel = Path("common/history/buildings")
        vanilla_dir = vanilla_root / rel
        mod_dir = mod_root / rel
        vanilla_dir.mkdir(parents=True, exist_ok=True)
        mod_dir.mkdir(parents=True, exist_ok=True)
        try:
            name = "01_south_europe.txt"
            (vanilla_dir / name).write_text("BUILDINGS = {}\n", encoding="utf-8")
            (mod_dir / name).write_text("BUILDINGS = {}\n", encoding="utf-8")
            effective = _effective_history_paths(
                mod_root, vanilla_root, str(rel).replace("\\", "/"), frozenset()
            )
            chosen = [path for path in effective if path.name == name]
            self.assertEqual(len(chosen), 1)
            self.assertEqual(chosen[0], mod_dir / name)
        finally:
            import shutil

            shutil.rmtree(mod_root, ignore_errors=True)
            shutil.rmtree(vanilla_root, ignore_errors=True)

    def test_empty_mod_override_is_recorded(self) -> None:
        mod_root = ROOT / "tmp_hist_src_mod"
        vanilla_root = ROOT / "tmp_hist_src_vanilla"
        rel = Path("common/history/buildings")
        vanilla_dir = vanilla_root / rel
        mod_dir = mod_root / rel
        vanilla_dir.mkdir(parents=True, exist_ok=True)
        mod_dir.mkdir(parents=True, exist_ok=True)
        try:
            name = "99_cleared.txt"
            (vanilla_dir / name).write_text(
                "BUILDINGS = {\n\ts:STATE_OLD = {\n\t}\n}\n", encoding="utf-8"
            )
            (mod_dir / name).write_text("", encoding="utf-8")
            rows = build_history_file_rows(mod_root, vanilla_root, frozenset())
            matched = [row for row in rows if row.filename == name]
            self.assertEqual(len(matched), 1)
            self.assertTrue(matched[0].is_empty)
        finally:
            import shutil

            shutil.rmtree(mod_root, ignore_errors=True)
            shutil.rmtree(vanilla_root, ignore_errors=True)

    def test_fallback_only_when_imported_state_missing_from_history(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE st_bld (id INTEGER PRIMARY KEY, state TEXT, tag TEXT, building TEXT);
            CREATE TABLE st_pop (id INTEGER PRIMARY KEY, state TEXT, tag TEXT, culture TEXT,
                religion TEXT, is_slaves INTEGER, size INTEGER);
            CREATE TABLE geo_state (state TEXT PRIMARY KEY);
            INSERT INTO st_bld (state, tag, building) VALUES ('STATE_ORPHAN', 'TAG', 'building_foo');
            INSERT INTO geo_state (state) VALUES ('STATE_ORPHAN');
            """
        )
        cfg = load_config()
        file_rows, source_rows = build_history_source_rows(
            cfg.vanilla,
            cfg.vanilla,
            frozenset(),
            ["STATE_ORPHAN", "STATE_OTHER"],
            conn,
        )
        orphan = next(row for row in source_rows if row.state == "STATE_ORPHAN")
        other = next(row for row in source_rows if row.state == "STATE_OTHER")
        self.assertTrue(orphan.bld_file.startswith("_fallback"))
        self.assertEqual(other.bld_file, "")
        fb_files = [row for row in file_rows if row.filename.startswith("_fallback")]
        self.assertEqual({row.category for row in fb_files}, {"buildings", "states"})
        conn.close()


if __name__ == "__main__":
    unittest.main()
