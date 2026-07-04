from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

COLLECT = Path(__file__).resolve().parents[1] / "src"
if str(COLLECT) not in sys.path:
    sys.path.insert(0, str(COLLECT))

from history_states_flat import (  # noqa: E402
    merge_history_states_blocks,
    parse_states_text,
    scan_states_file_brace_errors,
    scan_states_file_inner_non_standard_warnings,
    scan_states_file_no_create_state_warnings,
    scan_states_paths_no_create_state_warnings,
)


class HistoryStatesMergeTest(unittest.TestCase):
    def test_additive_block_injects_without_create_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_dir = root / "mod" / "common/history/states"
            vanilla_dir = root / "game" / "common/history/states"
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_states.txt").write_text(
                "STATES = {\n"
                "\ts:STATE_BEIJING = {\n"
                "\t\tcreate_state = {\n"
                "\t\t\tcountry = c:CHI\n"
                "\t\t\towned_provinces = { x038690 }\n"
                "\t\t}\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            (mod_dir / "hm_map.txt").write_text(
                "STATES = {\n"
                "\ts:STATE_BEIJING = {\n"
                "\t\tadd_state_trait = state_trait_great_canal\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            from game_content_resolver import merge_txt_paths

            paths, _ = merge_txt_paths(mod_dir, vanilla_dir)
            merged = merge_history_states_blocks(paths, mod_dir)
            self.assertIn("state_trait_great_canal", merged["STATE_BEIJING"])
            self.assertIn("country = c:CHI", merged["STATE_BEIJING"])
            meta, own = parse_states_text("\n".join(merged.values()))
            self.assertEqual(len(own), 1)
            self.assertEqual(own[0].tag, "CHI")

    def test_block_without_create_state_skipped_in_parse(self) -> None:
        text = (
            "s:STATE_TEST = {\n"
            "    add_homeland = cu:han\n"
            "    add_claim = c:CHI\n"
            "}\n"
        )
        meta, own = parse_states_text(text)
        self.assertEqual(meta, [])
        self.assertEqual(own, [])

    def test_block_without_create_state_emits_warning(self) -> None:
        text = (
            "s:STATE_TEST = {\n"
            "    add_homeland = cu:han\n"
            "    add_claim = c:CHI\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common/history/states/only_meta.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            warnings: list[str] = []
            log = type("L", (), {"warn": lambda _s, m: warnings.append(m)})()
            scan_states_file_no_create_state_warnings(path, mod_root, vanilla, log)
            self.assertEqual(len(warnings), 1)
            self.assertIn("非标准情况", warnings[0])
            self.assertIn("STATE_TEST", warnings[0])
            self.assertIn("无 create_state", warnings[0])

    def test_additive_block_without_create_state_does_not_warn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_dir = root / "mod" / "common/history/states"
            vanilla_dir = root / "game" / "common/history/states"
            mod_root = root / "mod"
            vanilla = root / "game"
            mod_dir.mkdir(parents=True)
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_states.txt").write_text(
                "STATES = {\n"
                "\ts:STATE_BEIJING = {\n"
                "\t\tcreate_state = {\n"
                "\t\t\tcountry = c:CHI\n"
                "\t\t\towned_provinces = { x038690 }\n"
                "\t\t}\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            (mod_dir / "hm_map.txt").write_text(
                "STATES = {\n"
                "\ts:STATE_BEIJING = {\n"
                "\t\tadd_state_trait = state_trait_great_canal\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )
            from game_content_resolver import merge_txt_paths

            paths, _ = merge_txt_paths(mod_dir, vanilla_dir)
            warnings: list[str] = []
            log = type("L", (), {"warn": lambda _s, m: warnings.append(m)})()
            scan_states_paths_no_create_state_warnings(
                paths, mod_dir, mod_root, vanilla, log
            )
            self.assertEqual(warnings, [])

    def test_set_variable_inside_state_emits_warning(self) -> None:
        text = (
            "s:STATE_KANTO = {\n"
            "\tcreate_state = {\n"
            "\t\tcountry = c:JAP\n"
            "\t\towned_provinces = { xEF9040 }\n"
            "\t}\n"
            "\tadd_homeland = cu:japanese\n"
            "\tset_variable = { name = daimyo_chain_id value = 0 }\n"
            "}\n"
        )
        meta, own = parse_states_text(text)
        self.assertEqual(len(meta), 1)
        self.assertEqual(len(own), 1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common/history/states/japan.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            warnings: list[str] = []
            log = type("L", (), {"warn": lambda _s, m: warnings.append(m)})()
            scan_states_file_inner_non_standard_warnings(path, mod_root, vanilla, log)
            self.assertEqual(len(warnings), 1)
            self.assertIn("非标准情况", warnings[0])
            self.assertIn("set_variable", warnings[0])
            self.assertIn("STATE_KANTO", warnings[0])

    def test_additive_state_trait_emits_warning(self) -> None:
        text = (
            "s:STATE_BEIJING = {\n"
            "\tadd_state_trait = state_trait_great_canal\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common/history/states/hm_map.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            warnings: list[str] = []
            log = type("L", (), {"warn": lambda _s, m: warnings.append(m)})()
            scan_states_file_inner_non_standard_warnings(path, mod_root, vanilla, log)
            self.assertEqual(len(warnings), 1)
            self.assertIn("add_state_trait", warnings[0])

    def test_standard_state_block_has_no_inner_warning(self) -> None:
        text = (
            "s:STATE_TEST = {\n"
            "\tcreate_state = {\n"
            "\t\tcountry = c:AAA\n"
            "\t\tstate_type = unincorporated\n"
            "\t\towned_provinces = { x12345678 }\n"
            "\t}\n"
            "\tadd_homeland = cu:han\n"
            "\tadd_claim = c:CHI\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common/history/states/ok.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            warnings: list[str] = []
            log = type("L", (), {"warn": lambda _s, m: warnings.append(m)})()
            scan_states_file_inner_non_standard_warnings(path, mod_root, vanilla, log)
            self.assertEqual(warnings, [])

    def test_brace_error_still_scanned_without_create_state(self) -> None:
        text = (
            "s:STATE_BAD = {\n"
            "    add_homeland = cu:han\n"
            "s:STATE_OTHER = {\n"
            "    create_state = { country = c:AAA owned_provinces = { x11111111 } }\n"
            "}\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common/history/states/bad.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            log = type("L", (), {"error": lambda _s, m: errors.append(m)})()
            scan_states_file_brace_errors(path, mod_root, vanilla, log)
            self.assertEqual(len(errors), 1)
            self.assertIn("STATE_BAD", errors[0])
            self.assertIn("括号不匹配", errors[0])


if __name__ == "__main__":
    unittest.main()
