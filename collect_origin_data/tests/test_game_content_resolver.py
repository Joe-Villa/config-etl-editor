from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from game_content_resolver import (  # noqa: E402
    ContentSource,
    load_mod_replace_paths,
    merge_paradox_blocks,
    merge_txt_paths,
    read_merged_paradox_blocks,
    resolve_merged_content,
)


class GameContentResolverTests(unittest.TestCase):
    def test_missing_mod_dir_uses_vanilla(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            mod_root.mkdir()
            vanilla = root / "game"
            rel = "common/history/pops"
            vanilla_dir = vanilla / rel
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_pops.txt").write_text("POPS = { }", encoding="utf-8")

            merged = resolve_merged_content(mod_root, rel, vanilla)
            self.assertEqual(merged.source, ContentSource.VANILLA)
            self.assertEqual(len(merged.paths), 1)
            self.assertEqual(merged.paths[0].name, "00_pops.txt")

    def test_mod_empty_overlay_counts_as_mod(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "game"
            rel = "common/history/buildings"
            vanilla_dir = vanilla / rel
            mod_dir = mod_root / rel
            vanilla_dir.mkdir(parents=True)
            mod_dir.mkdir(parents=True)
            (vanilla_dir / "00_west_europe.txt").write_text(
                'BUILDINGS = { s:STATE_X = { region_state:CHI = { create_building = { building = "vanilla" level = 1 } } } } }',
                encoding="utf-8",
            )
            (vanilla_dir / "01_south_europe.txt").write_text("BUILDINGS = { }", encoding="utf-8")
            (mod_dir / "00_west_europe.txt").write_text("", encoding="utf-8")
            (mod_dir / "01_south_europe.txt").write_text("", encoding="utf-8")
            (mod_dir / "iw_buildings_roundtrip.txt").write_text(
                'BUILDINGS = { s:STATE_Y = { region_state:CHI = { create_building = { building = "mod_only" level = 2 } } } } }',
                encoding="utf-8",
            )

            paths, source = merge_txt_paths(mod_dir, vanilla_dir)
            self.assertEqual(source, ContentSource.MOD)
            self.assertEqual({p.name for p in paths}, {
                "00_west_europe.txt",
                "01_south_europe.txt",
                "iw_buildings_roundtrip.txt",
            })
            self.assertEqual(paths[0].parent, mod_dir)
            self.assertEqual(paths[1].parent, mod_dir)

    def test_partial_mod_overlay_is_mod_part(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vanilla = root / "game"
            mod_dir = root / "mod" / "common/history/buildings"
            vanilla_dir = vanilla / "common/history/buildings"
            vanilla_dir.mkdir(parents=True)
            mod_dir.mkdir(parents=True)
            (vanilla_dir / "00_west_europe.txt").write_text("BUILDINGS = { }", encoding="utf-8")
            (vanilla_dir / "01_south_europe.txt").write_text("BUILDINGS = { }", encoding="utf-8")
            (mod_dir / "00_west_europe.txt").write_text("BUILDINGS = { }", encoding="utf-8")

            paths, source = merge_txt_paths(mod_dir, vanilla_dir)
            self.assertEqual(source, ContentSource.MOD_PART)
            by_name = {p.name: p for p in paths}
            self.assertEqual(by_name["00_west_europe.txt"].parent, mod_dir)
            self.assertEqual(by_name["01_south_europe.txt"].parent, vanilla_dir)

    def test_force_vanilla_skips_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "game"
            rel = "common/history/buildings"
            mod_dir = mod_root / rel
            vanilla_dir = vanilla / rel
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (mod_dir / "patch.txt").write_text("BUILDINGS = { mod = yes }", encoding="utf-8")
            (vanilla_dir / "00_states.txt").write_text("BUILDINGS = { vanilla = yes }", encoding="utf-8")

            merged = resolve_merged_content(mod_root, rel, vanilla, force_vanilla=True)
            self.assertEqual(merged.source, ContentSource.VANILLA)
            self.assertEqual([p.name for p in merged.paths], ["00_states.txt"])

    def test_replace_paths_ignores_vanilla(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "game"
            rel = "common/history/buildings"
            mod_dir = mod_root / rel
            vanilla_dir = vanilla / rel
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_west_europe.txt").write_text(
                "BUILDINGS = { vanilla = yes }",
                encoding="utf-8",
            )
            (vanilla_dir / "01_south_europe.txt").write_text(
                "BUILDINGS = { vanilla = yes }",
                encoding="utf-8",
            )
            (mod_dir / "iw_buildings.txt").write_text(
                "BUILDINGS = { mod = yes }",
                encoding="utf-8",
            )

            merged = resolve_merged_content(
                mod_root,
                rel,
                vanilla,
                replace_paths=frozenset({rel}),
            )
            self.assertEqual(merged.source, ContentSource.MOD)
            self.assertEqual([p.name for p in merged.paths], ["iw_buildings.txt"])
            self.assertTrue(all(path.parent == mod_dir for path in merged.paths))

    def test_replace_paths_not_listed_still_merges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "game"
            rel = "common/history/pops"
            mod_dir = mod_root / rel
            vanilla_dir = vanilla / rel
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_pops.txt").write_text("POPS = { vanilla = yes }", encoding="utf-8")
            (mod_dir / "01_pops.txt").write_text("POPS = { mod = yes }", encoding="utf-8")

            merged = resolve_merged_content(
                mod_root,
                rel,
                vanilla,
                replace_paths=frozenset({"common/history/buildings"}),
            )
            self.assertEqual(merged.source, ContentSource.MOD_PART)
            self.assertEqual({p.name for p in merged.paths}, {"00_pops.txt", "01_pops.txt"})

    def test_load_mod_replace_paths_from_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod_root = Path(tmp) / "mod"
            metadata_dir = mod_root / ".metadata"
            metadata_dir.mkdir(parents=True)
            (metadata_dir / "metadata.json").write_text(
                """
                {
                  "game_custom_data": {
                    "replace_paths": [
                      "common/history/states",
                      "/common/history/pops/"
                    ]
                  }
                }
                """,
                encoding="utf-8",
            )
            self.assertEqual(
                load_mod_replace_paths(mod_root),
                frozenset({"common/history/states", "common/history/pops"}),
            )

    def test_load_mod_replace_paths_missing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod_root = Path(tmp) / "mod"
            mod_root.mkdir()
            self.assertEqual(load_mod_replace_paths(mod_root), frozenset())

    def test_merge_paradox_blocks_mod_overrides_vanilla(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_dir = root / "mod" / "common/cultures"
            vanilla_dir = root / "game" / "common/cultures"
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_cultures.txt").write_text(
                "north_german = { religion = protestant color = { 0.1 0.1 0.1 } }\n",
                encoding="utf-8",
            )
            (mod_dir / "patch_cultures.txt").write_text(
                "north_german = { religion = catholic color = { 0.9 0.9 0.9 } }\n",
                encoding="utf-8",
            )
            paths, _ = merge_txt_paths(mod_dir, vanilla_dir)
            merged = merge_paradox_blocks(paths, mod_dir, r"[a-z][a-z0-9_]*")
            self.assertEqual(set(merged), {"north_german"})
            self.assertIn("religion = catholic", merged["north_german"])

    def test_merge_paradox_blocks_dedup_within_mod_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod_dir = Path(tmp) / "common/cultures"
            mod_dir.mkdir(parents=True)
            (mod_dir / "000_early.txt").write_text(
                "british = { religion = protestant color = { 0.2 0.2 0.2 } }\n",
                encoding="utf-8",
            )
            (mod_dir / "zzz_late.txt").write_text(
                "british = { religion = catholic color = { 0.8 0.8 0.8 } }\n",
                encoding="utf-8",
            )
            paths = sorted(mod_dir.iterdir())
            merged = merge_paradox_blocks(paths, mod_dir, r"[a-z][a-z0-9_]*")
            self.assertEqual(len(merged), 1)
            self.assertIn("religion = catholic", merged["british"])

    def test_read_merged_paradox_blocks_same_filename_uses_mod_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_dir = root / "mod" / "common/cultures"
            vanilla_dir = root / "game" / "common/cultures"
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_cultures.txt").write_text(
                "french = { religion = catholic color = { 0.1 0.1 0.1 } }\n",
                encoding="utf-8",
            )
            (mod_dir / "00_cultures.txt").write_text(
                "french = { religion = protestant color = { 0.5 0.5 0.5 } }\n",
                encoding="utf-8",
            )
            paths, _ = merge_txt_paths(mod_dir, vanilla_dir)
            text = read_merged_paradox_blocks(paths, mod_dir, r"[a-z][a-z0-9_]*")
            self.assertIn("religion = protestant", text)
            self.assertNotIn("religion = catholic", text)

    def test_find_block_end_ignores_braces_in_line_comments(self) -> None:
        from vic3_assign import find_block_end

        text = "s:STATE_X = {\n\tcreate_state = { country = c:AAA }\n# add_claim = c:JNR\t}\n}"
        start = text.index("{")
        end = find_block_end(text, start)
        self.assertEqual(end, len(text) - 1)
        self.assertIn("# add_claim = c:JNR", text[: end + 1])

    def test_merge_paradox_blocks_state_prefix_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_dir = root / "mod" / "common/history/states"
            vanilla_dir = root / "game" / "common/history/states"
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_europe.txt").write_text(
                "STATES = {\n\ts:STATE_X = { add_homeland = cu:north_german }\n}",
                encoding="utf-8",
            )
            (mod_dir / "patch_states.txt").write_text(
                "STATES = {\n\ts:STATE_X = { add_homeland = cu:south_german }\n}",
                encoding="utf-8",
            )
            paths, _ = merge_txt_paths(mod_dir, vanilla_dir)
            merged = merge_paradox_blocks(
                paths,
                mod_dir,
                r"STATE_\w+",
                line_prefix="s:",
            )
            self.assertEqual(set(merged), {"STATE_X"})
            self.assertIn("south_german", merged["STATE_X"])
            self.assertNotIn("north_german", merged["STATE_X"])

    def test_merge_paradox_blocks_combine_history_pops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_dir = root / "mod" / "common/history/pops"
            vanilla_dir = root / "game" / "common/history/pops"
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_europe.txt").write_text(
                "s:STATE_X = {\n"
                "\tregion_state:AAA = {\n"
                "\t\tcreate_pop = { culture = british size = 1000 }\n"
                "\t}\n"
                "}",
                encoding="utf-8",
            )
            (mod_dir / "patch_pops.txt").write_text(
                "s:STATE_X = {\n"
                "\tregion_state:BBB = {\n"
                "\t\tcreate_pop = { culture = french size = 500 }\n"
                "\t}\n"
                "}",
                encoding="utf-8",
            )
            paths, _ = merge_txt_paths(mod_dir, vanilla_dir)
            merged = merge_paradox_blocks(
                paths,
                mod_dir,
                r"STATE_\w+",
                line_prefix="s:",
                combine_duplicates=True,
            )
            self.assertEqual(set(merged), {"STATE_X"})
            block = merged["STATE_X"]
            self.assertIn("region_state:AAA", block)
            self.assertIn("region_state:BBB", block)
            self.assertIn("british", block)
            self.assertIn("french", block)

    def test_merge_paradox_blocks_combine_history_buildings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_dir = root / "mod" / "common/history/buildings"
            vanilla_dir = root / "game" / "common/history/buildings"
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_europe.txt").write_text(
                "BUILDINGS = {\n"
                "\ts:STATE_X = {\n"
                "\t\tregion_state:AAA = {\n"
                "\t\t\tcreate_building = { building = building_farm level = 1 }\n"
                "\t\t}\n"
                "\t}\n"
                "}",
                encoding="utf-8",
            )
            (mod_dir / "patch_buildings.txt").write_text(
                "BUILDINGS = {\n"
                "\ts:STATE_X = {\n"
                "\t\tregion_state:BBB = {\n"
                "\t\t\tcreate_building = { building = building_mine level = 2 }\n"
                "\t\t}\n"
                "\t}\n"
                "}",
                encoding="utf-8",
            )
            paths, _ = merge_txt_paths(mod_dir, vanilla_dir)
            merged = merge_paradox_blocks(
                paths,
                mod_dir,
                r"STATE_\w+",
                line_prefix="s:",
                combine_duplicates=True,
            )
            block = merged["STATE_X"]
            self.assertIn("region_state:AAA", block)
            self.assertIn("region_state:BBB", block)
            self.assertIn("building_farm", block)
            self.assertIn("building_mine", block)


if __name__ == "__main__":
    unittest.main()
