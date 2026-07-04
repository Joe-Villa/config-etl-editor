"""Tests for import error formatting and content scans."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

COLLECT = Path(__file__).resolve().parents[1] / "src"
if str(COLLECT) not in sys.path:
    sys.path.insert(0, str(COLLECT))

from import_context import format_import_error, format_import_warning, line_at  # noqa: E402
from history_states_flat import (  # noqa: E402
    parse_states_text,
    scan_states_file_brace_errors,
    scan_states_file_create_state_errors,
)


class ImportContextTest(unittest.TestCase):
    def test_line_at(self) -> None:
        text = "a\nb\nc"
        self.assertEqual(line_at(text, 0), 1)
        self.assertEqual(line_at(text, 2), 2)
        self.assertEqual(line_at(text, 4), 3)

    def test_format_import_error(self) -> None:
        msg = format_import_error(
            "mod",
            "common/history/states",
            "00_states.txt",
            42,
            "解析开局州历史 create_state（州 STATE_X）",
            "缺少 country 字段，无法确定归属 tag",
        )
        self.assertIn("[mod]", msg)
        self.assertIn("common/history/states/00_states.txt", msg)
        self.assertIn("第 42 行", msg)
        self.assertIn("缺少 country", msg)

    def test_format_import_warning(self) -> None:
        msg = format_import_warning(
            "mod",
            "common/history/states",
            "00_states.txt",
            42,
            "解析开局州历史块（州 STATE_X）",
            "块内无 create_state，本程序不处理此类写法，已跳过",
        )
        self.assertIn("[mod]", msg)
        self.assertIn("common/history/states/00_states.txt", msg)
        self.assertIn("第 42 行", msg)
        self.assertIn("非标准情况", msg)
        self.assertIn("无 create_state", msg)


class CreateStateScanTest(unittest.TestCase):
    def test_missing_country_logs_and_skips_in_merged_parse(self) -> None:
        text = (
            "s:STATE_TEST = {\n"
            "    create_state = {\n"
            "        owned_provinces = { x12345678 }\n"
            "    }\n"
            "}\n"
        )
        meta, own = parse_states_text(text)
        self.assertEqual(len(meta), 1)
        self.assertEqual(own, [])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "history" / "states" / "test.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            log = type("L", (), {"error": lambda _s, m: errors.append(m)})()

            scan_states_file_create_state_errors(path, mod_root, vanilla, log)
            self.assertEqual(len(errors), 1)
            self.assertIn("[mod]", errors[0])
            self.assertIn("test.txt", errors[0])
            self.assertIn("STATE_TEST", errors[0])

    def test_uppercase_country_prefix_parses(self) -> None:
        text = (
            "s:STATE_TEST = {\n"
            "    create_state = {\n"
            "        country = C:A01\n"
            "        owned_provinces = { x12345678 }\n"
            "    }\n"
            "}\n"
        )
        meta, own = parse_states_text(text)
        self.assertEqual(len(meta), 1)
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0].tag, "A01")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "history" / "states" / "upper.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            log = type("L", (), {"error": lambda _s, m: errors.append(m)})()
            scan_states_file_create_state_errors(path, mod_root, vanilla, log)
            self.assertEqual(errors, [])


class HistoryStatesReplaceOrCreateTest(unittest.TestCase):
    def test_replace_or_create_state_header_parses(self) -> None:
        text = (
            "s:REPLACE_OR_CREATE:STATE_TEST = {\n"
            "    create_state = {\n"
            "        country = c:AAA\n"
            "        owned_provinces = { x12345678 }\n"
            "    }\n"
            "}\n"
        )
        meta, own = parse_states_text(text)
        self.assertEqual(len(meta), 1)
        self.assertEqual(meta[0].state, "STATE_TEST")
        self.assertEqual(len(own), 1)
        self.assertEqual(own[0].tag, "AAA")


class BraceMismatchScanTest(unittest.TestCase):
    def test_comment_with_brace_does_not_false_positive(self) -> None:
        text = (
            "s:STATE_A = {\n"
            "    # note: stray } in comment\n"
            "    create_state = { country = c:AAA owned_provinces = { x11111111 } }\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "history" / "states" / "ok.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            log = type("L", (), {"error": lambda _s, m: errors.append(m)})()
            scan_states_file_brace_errors(path, mod_root, vanilla, log)
            self.assertEqual(errors, [])

    def test_swallowed_state_block_logs_error(self) -> None:
        text = (
            "s:STATE_A = {\n"
            "    create_state = {\n"
            "        country = c:AAA\n"
            "        owned_provinces = { x11111111 }\n"
            "    add_homeland = cu:british\n"
            "}\n"
            "s:STATE_B = {\n"
            "    create_state = { country = c:BBB owned_provinces = { x22222222 } }\n"
            "    add_homeland = cu:french\n"
            "}\n"
            "}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "vanilla"
            path = mod_root / "common" / "history" / "states" / "bad.txt"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

            errors: list[str] = []
            log = type("L", (), {"error": lambda _s, m: errors.append(m)})()
            scan_states_file_brace_errors(path, mod_root, vanilla, log)
            self.assertEqual(len(errors), 1)
            self.assertIn("STATE_A", errors[0])
            self.assertIn("STATE_B", errors[0])
            self.assertIn("括号不匹配", errors[0])


if __name__ == "__main__":
    unittest.main()
