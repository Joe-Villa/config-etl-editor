"""Tests for launcher defaults and build job guards."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_paths import default_save_sqlite  # noqa: E402
from interactive_map.build_job import (  # noqa: E402
    BuildJob,
    default_vanilla_game_path,
    launcher_defaults,
    launcher_gate_defaults,
)
from interactive_map.server_state import MapServerState  # noqa: E402


class LauncherDefaultsTest(unittest.TestCase):
    def test_defaults_use_package_root(self) -> None:
        defaults = launcher_defaults()
        cwd = Path(defaults["cwd"])
        self.assertTrue((cwd / "interactive_map").is_dir())
        self.assertEqual(defaults["output"], str(default_save_sqlite()))

    def test_gate_defaults_include_cwd(self) -> None:
        gate = launcher_gate_defaults()
        full = launcher_defaults()
        self.assertEqual(gate["output"], full["output"])
        self.assertEqual(gate["vanilla"], full["vanilla"])
        self.assertEqual(gate["cwd"], full["cwd"])

        self.assertIn("Victoria 3", default_vanilla_game_path())
        self.assertTrue(default_vanilla_game_path().endswith("\\game"))


class BuildJobGuardTest(unittest.TestCase):
    def test_reject_existing_output_file(self) -> None:
        job = BuildJob()
        state = MapServerState()
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "map_editor.sqlite"
            existing.write_bytes(b"sqlite")
            with self.assertRaises(FileExistsError):
                job.start(
                    vanilla=ROOT,
                    mod_root=None,
                    output=existing,
                    server_state=state,
                )
        state.close()


if __name__ == "__main__":
    unittest.main()
