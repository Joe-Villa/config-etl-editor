from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from collector import collect, derive_output_dir_name  # noqa: E402
from config import load_config  # noqa: E402
from constants import ORIGIN_DB  # noqa: E402
from game_content_resolver import ContentSource, resolve_merged_content  # noqa: E402


class CollectOriginDataTests(unittest.TestCase):
    def test_derive_output_dir_name(self) -> None:
        self.assertEqual(
            derive_output_dir_name(
                Path("/home/.steam/.../content/529340/3346844497")
            ),
            "3346844497",
        )

    def test_resolve_missing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod_root = Path(tmp) / "mod"
            mod_root.mkdir()
            vanilla = Path(tmp) / "game"
            (vanilla / "common/history/pops").mkdir(parents=True)
            merged = resolve_merged_content(mod_root, "common/history/pops", vanilla)
            self.assertEqual(merged.source, ContentSource.VANILLA)

    def test_collect_vanilla_as_mod_root(self) -> None:
        config = load_config()
        if not config.vanilla.is_dir():
            self.skipTest("未找到原版游戏目录")
        summary = collect(
            config.vanilla,
            run_id="_test-vanilla-run",
            config=config,
        )
        self.assertEqual(summary.run_id, "_test-vanilla-run")
        self.assertTrue((summary.output_dir / ORIGIN_DB).is_file())
        self.assertTrue(summary.metadata_path.is_file())
        meta = json.loads(summary.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["run_id"], "_test-vanilla-run")
        if config.metadata_hide_full_path:
            self.assertNotIn("mod_root", meta)
            self.assertNotIn("vanilla_game", meta)
            self.assertNotIn("output_dir", meta)
            self.assertIn("inputs", meta["tables"]["origin"])
            self.assertIn("pops", meta["tables"]["origin"]["inputs"])
        else:
            self.assertIn("mod_root", meta)
        self.assertEqual(len(meta["tables"]), 1)
        self.assertIn("origin", meta["tables"])
        self.assertNotIn("history_pops_flat", meta["tables"])

        import shutil

        shutil.rmtree(summary.output_dir)


class RunPipelineTests(unittest.TestCase):
    def test_run_pipeline(self) -> None:
        config = load_config()
        if not config.vanilla.is_dir():
            self.skipTest("未找到原版游戏目录")

        tool_dir = Path(__file__).resolve().parent.parent / "tool"
        if str(tool_dir) not in sys.path:
            sys.path.insert(0, str(tool_dir))

        from merge_tables import export_run_excel  # noqa: E402

        summary = collect(
            config.vanilla,
            run_id="_test-run-pipeline",
            config=config,
        )
        excel_path, db_count, sheet_count = export_run_excel(summary.output_dir)
        self.assertEqual(db_count, 1)
        self.assertGreater(sheet_count, 8)
        self.assertTrue(excel_path.is_file())

        import shutil

        shutil.rmtree(summary.output_dir)
        if excel_path.is_file():
            excel_path.unlink()


if __name__ == "__main__":
    unittest.main()
