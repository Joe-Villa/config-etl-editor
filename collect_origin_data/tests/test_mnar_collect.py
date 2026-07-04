from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from constants import ORIGIN_DB  # noqa: E402
from collector import collect  # noqa: E402
from config import load_config  # noqa: E402

MNAR_MOD = Path(__file__).resolve().parents[2].parent / "MNAR"


class MnarCollectTests(unittest.TestCase):
    def test_mnar_collect_completes_with_skips(self) -> None:
        if not MNAR_MOD.is_dir():
            self.skipTest("未找到 MNAR 模组")
        config = load_config()
        summary = collect(MNAR_MOD, run_id="_test-mnar", config=config)
        db_path = summary.output_dir / ORIGIN_DB
        self.assertTrue(db_path.is_file())

        import sqlite3

        conn = sqlite3.connect(db_path)
        building_count = conn.execute(
            "SELECT COUNT(*) FROM tag__state__building"
        ).fetchone()[0]
        conn.close()
        self.assertGreater(building_count, 0)

        import shutil

        shutil.rmtree(summary.output_dir)


if __name__ == "__main__":
    unittest.main()
