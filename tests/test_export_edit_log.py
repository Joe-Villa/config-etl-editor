"""Tests for edit log export."""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.log import export_edit_log, write_batch  # noqa: E402


class ExportEditLogTest(unittest.TestCase):
    def test_export_empty_log(self) -> None:
        conn = sqlite3.connect(":memory:")
        payload = export_edit_log(conn)
        self.assertEqual(payload["batch_count"], 0)
        self.assertEqual(payload["batches"], [])

    def test_export_includes_steps_and_undo(self) -> None:
        conn = sqlite3.connect(":memory:")
        batch_id = write_batch(
            conn,
            summary="test op",
            payload={"op": "demo"},
            steps=[("demo_op", {"x": 1}, {"before": 0})],
        )
        payload = export_edit_log(conn)
        self.assertEqual(payload["batch_count"], 1)
        batch = payload["batches"][0]
        self.assertEqual(batch["id"], batch_id)
        self.assertEqual(batch["summary"], "test op")
        self.assertEqual(batch["payload"], {"op": "demo"})
        self.assertEqual(len(batch["steps"]), 1)
        self.assertEqual(batch["steps"][0]["op"], "demo_op")
        self.assertEqual(batch["steps"][0]["args"], {"x": 1})
        self.assertEqual(batch["steps"][0]["undo"], {"before": 0})
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
