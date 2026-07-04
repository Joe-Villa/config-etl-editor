"""Smoke tests for bootstrap / runtime package split."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime_deps

runtime_deps.register()

from bootstrap import DatabaseArtifact, build_map_db  # noqa: E402
from bootstrap.build_job import BuildJob, launcher_gate_defaults  # noqa: E402
from interactive_map.build_job import BuildJob as LegacyBuildJob  # noqa: E402
from interactive_map.server_state import MapServerState as LegacyServerState  # noqa: E402
from runtime import MapServerState, MapSession, open_session  # noqa: E402


class BootstrapRuntimeSplitTest(unittest.TestCase):
    def test_legacy_shims_match_new_modules(self) -> None:
        self.assertIs(LegacyBuildJob, BuildJob)
        self.assertIs(LegacyServerState, MapServerState)

    def test_launcher_defaults_shape(self) -> None:
        defaults = launcher_gate_defaults()
        self.assertIn("cwd", defaults)
        self.assertIn("output", defaults)
        self.assertIn("vanilla", defaults)

    def test_server_state_starts_unloaded(self) -> None:
        state = MapServerState()
        self.assertIsNone(state.session)
        payload = state.status_json()
        self.assertFalse(payload["loaded"])
        self.assertIn("build", payload)

    def test_public_entrypoints(self) -> None:
        self.assertTrue(callable(build_map_db))
        self.assertTrue(callable(open_session))
        self.assertTrue(hasattr(MapSession, "open"))

    def test_map_db_package_on_disk(self) -> None:
        map_db_dir = ROOT / "map_db"
        self.assertTrue((map_db_dir / "build_db.py").is_file())
        self.assertTrue((map_db_dir / "schema.sql").is_file())
        self.assertFalse((ROOT / "src").exists())
        self.assertFalse((ROOT / "build").exists())
        self.assertFalse((ROOT / "schema.sql").exists())


if __name__ == "__main__":
    unittest.main()
