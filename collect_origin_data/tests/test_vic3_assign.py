"""Tests for Paradox line-comment masking."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from vic3_assign import find_block_end, mask_line_comments, prepare_game_content, read_game_content  # noqa: E402


class Vic3AssignCommentTest(unittest.TestCase):
    def test_mask_preserves_length_and_line_numbers(self) -> None:
        text = "a\n# comment\nb"
        masked = mask_line_comments(text)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.splitlines()[1].strip(), "")
        self.assertIn("b", masked)

    def test_find_block_end_ignores_commented_braces(self) -> None:
        text = prepare_game_content(
            "outer = {\n"
            "    # stray { }\n"
            "    value = 1\n"
            "}\n"
        )
        start = text.index("{")
        end = find_block_end(text, start)
        self.assertEqual(text[end], "}")
        self.assertIn("value = 1", text[start : end + 1])

    def test_read_game_content_masks_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.txt"
            path.write_text("key = value\n# key = { broken }\n", encoding="utf-8")
            masked = read_game_content(path)
            self.assertNotIn("broken", masked)
            self.assertIn("key = value", masked)


if __name__ == "__main__":
    unittest.main()
