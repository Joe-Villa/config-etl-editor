"""Tests for full-database snapshot save/restore."""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.db_snapshot import (  # noqa: E402
    INITIAL_SNAPSHOT_LABEL,
    create_initial_snapshot,
    create_snapshot,
    list_snapshots,
    restore_snapshot,
    snapshots_dir,
)
from interactive_map.server_state import MapServerState  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


class DbSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "map_db"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="map-snapshot-test-"))
        self.db_path = self.tmp / "map_editor.sqlite"
        shutil.copy2(DB, self.db_path)
        self.snap_dir = snapshots_dir(self.db_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_and_list_snapshot(self) -> None:
        entry = create_snapshot(self.db_path, label="测试点")
        self.assertTrue((self.snap_dir / f"{entry['id']}.sqlite").is_file())
        snapshots = list_snapshots(self.db_path)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["label"], "测试点")

    def test_restore_reverts_database_change(self) -> None:
        create_snapshot(self.db_path, label="before")
        conn = sqlite3.connect(self.db_path)
        before = conn.execute("SELECT COUNT(*) FROM st").fetchone()[0]
        conn.execute(
            """
            INSERT INTO st (state, tag, state_type)
            VALUES ('STATE_TEST_SNAPSHOT', 'TST', 'incorporated')
            """
        )
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM st").fetchone()[0]
        conn.close()
        self.assertEqual(after, before + 1)

        snapshot_id = list_snapshots(self.db_path)[0]["id"]
        restore_snapshot(self.db_path, snapshot_id)

        conn = sqlite3.connect(self.db_path)
        restored = conn.execute("SELECT COUNT(*) FROM st").fetchone()[0]
        conn.close()
        self.assertEqual(restored, before)

    def test_empty_label_uses_current_time(self) -> None:
        entry = create_snapshot(self.db_path, label="")
        self.assertRegex(entry["label"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_initial_snapshot_label(self) -> None:
        entry = create_initial_snapshot(self.db_path)
        self.assertEqual(entry["label"], INITIAL_SNAPSHOT_LABEL)
        self.assertTrue(entry["auto"])

        entry = create_initial_snapshot(self.db_path)
        self.assertEqual(entry["label"], INITIAL_SNAPSHOT_LABEL)
        self.assertTrue(entry["auto"])

    def test_server_state_restore_reloads_session(self) -> None:
        create_snapshot(self.db_path, label="baseline")
        state = MapServerState()
        session = state.load(self.db_path)
        session.conn.execute(
            """
            INSERT INTO st (state, tag, state_type)
            VALUES ('STATE_TEST_SERVER', 'TST', 'incorporated')
            """
        )
        session.conn.commit()
        before = session.conn.execute("SELECT COUNT(*) FROM st").fetchone()[0]
        snapshot_id = list_snapshots(self.db_path)[0]["id"]

        result = state.restore_db_snapshot(snapshot_id)

        self.assertEqual(result["snapshot"]["id"], snapshot_id)
        restored = state.session.conn.execute("SELECT COUNT(*) FROM st").fetchone()[0]
        self.assertLess(restored, before)
        state.close()


if __name__ == "__main__":
    unittest.main()
