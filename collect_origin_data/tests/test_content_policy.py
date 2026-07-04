from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from content_policy import ContentPolicy, content_policy_from_dict  # noqa: E402
from game_content_resolver import ContentSource, resolve_merged_content  # noqa: E402


class ContentPolicyTests(unittest.TestCase):
    def test_mod_only_forces_other_paths_to_vanilla(self) -> None:
        policy = content_policy_from_dict({"mod_only": ["map_data/state_regions"]})
        self.assertTrue(policy.uses_mod("map_data/state_regions"))
        self.assertFalse(policy.uses_mod("common/history/buildings"))
        self.assertIn(
            "common/history/buildings",
            policy.forced_vanilla_paths(),
        )

    def test_force_vanilla_paths(self) -> None:
        policy = content_policy_from_dict(
            {"force_vanilla": ["common/history/buildings"]}
        )
        self.assertFalse(policy.uses_mod("common/history/buildings"))
        self.assertTrue(policy.uses_mod("common/history/pops"))

    def test_resolve_with_force_vanilla(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod_root = root / "mod"
            vanilla = root / "game"
            rel = "common/history/buildings"
            mod_dir = mod_root / rel
            mod_dir.mkdir(parents=True)
            (mod_dir / "patch.txt").write_text(
                'BUILDINGS = { s:STATE_X = { region_state:CHI = { create_building = { building = "new_small_town" level = 1 } } } } }',
                encoding="utf-8",
            )
            vanilla_dir = vanilla / rel
            vanilla_dir.mkdir(parents=True)
            (vanilla_dir / "00_states.txt").write_text("BUILDINGS = { }", encoding="utf-8")

            merged = resolve_merged_content(
                mod_root, rel, vanilla, force_vanilla=True
            )
            self.assertEqual(merged.source, ContentSource.VANILLA)
            self.assertEqual(merged.content_dir, vanilla_dir)


if __name__ == "__main__":
    unittest.main()
