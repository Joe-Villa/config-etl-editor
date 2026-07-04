"""Tests for mod .metadata replace_paths in map editor content resolution."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "map_db"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_db import build_map_db  # noqa: E402
from content_paths import mod_replace_paths, resolve_game_content  # noqa: E402
from editor_config import load_config  # noqa: E402
from parse_ref import load_state_regions  # noqa: E402


class ReplacePathsTest(unittest.TestCase):
    def test_missing_metadata_has_no_replace_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mod_root = Path(tmp) / "mod"
            mod_root.mkdir()
            self.assertEqual(mod_replace_paths(mod_root), frozenset())

    def test_replace_paths_uses_mod_only_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "game"
            rel = "map_data/state_regions"
            vanilla_dir = vanilla / rel
            mod_dir = mod_root / rel
            vanilla_dir.mkdir(parents=True)
            mod_dir.mkdir(parents=True)
            (vanilla_dir / "00_west_europe.txt").write_text(
                "STATE_WEST_EUROPE = { id = 1 provinces = { x111111 } }",
                encoding="utf-8",
            )
            (mod_dir / "00_states.txt").write_text(
                "STATE_MOD_ONLY = { id = 2 provinces = { x222222 } }",
                encoding="utf-8",
            )
            metadata_dir = mod_root / ".metadata"
            metadata_dir.mkdir()
            (metadata_dir / "metadata.json").write_text(
                '{"game_custom_data":{"replace_paths":["map_data/state_regions"]}}',
                encoding="utf-8",
            )
            replace_paths = mod_replace_paths(mod_root)
            merged = resolve_game_content(mod_root, rel, vanilla, replace_paths)
            self.assertEqual([p.name for p in merged.paths], ["00_states.txt"])
            regions = load_state_regions(mod_root, vanilla, replace_paths)
            self.assertEqual([r.state for r in regions], ["STATE_MOD_ONLY"])

    def test_jiuri_mod_unowned_land_state_errors_drop(self) -> None:
        mod = Path(
            "/home/liulingda/.steam/debian-installation/steamapps/workshop/content/529340/3260268786"
        )
        if not mod.is_dir():
            self.skipTest("jiuri mod 不在本机")

        out = Path(tempfile.mktemp(suffix=".sqlite"))
        try:
            log = build_map_db(mod, out, load_config(), fail_on_error=False)
            whole_state_errors = [
                msg for msg in log.errors if "陆地州" in msg and "未被任何 tag 拥有" in msg
            ]
            self.assertLessEqual(len(whole_state_errors), 2)
        finally:
            if out.is_file():
                out.unlink()


if __name__ == "__main__":
    unittest.main()
