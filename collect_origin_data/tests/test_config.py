from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import load_config  # noqa: E402


class CollectConfigTests(unittest.TestCase):
    def test_missing_config_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_config(Path("/nonexistent/config.json"))

    def test_load_force_to_vanilla(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "metadata_hide_full_path": False,
                        "vanilla": "/tmp/game",
                        "force_to_vanilla": ["map_data/state_regions"],
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertFalse(config.metadata_hide_full_path)
            self.assertEqual(config.vanilla, Path("/tmp/game"))
            self.assertEqual(
                config.force_to_vanilla,
                frozenset({"map_data/state_regions"}),
            )
            self.assertFalse(config.content_policy().uses_mod("map_data/state_regions"))

    def test_unknown_force_to_vanilla_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "vanilla": "/tmp/game",
                        "force_to_vanilla": ["not/a/real/path"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
