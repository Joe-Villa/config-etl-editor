from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hub_localization import apply_hub_names_to_regions, load_hub_names  # noqa: E402
from state_region_flat import FlatStateRegion, parse_state_block  # noqa: E402


class HubLocalizationTests(unittest.TestCase):
    def test_apply_hub_names(self) -> None:
        row = parse_state_block(
            "STATE_NORTH_RHINE",
            'id = 64\nprovinces = { "x1" }\ncity = "x9F4072"\n',
        )
        apply_hub_names_to_regions(
            [row],
            {("STATE_NORTH_RHINE", "city"): "科隆"},
        )
        self.assertEqual(row.city_name, "科隆")
        self.assertEqual(row.port_name, "")

    def test_load_hub_names_from_vanilla(self) -> None:
        from config import load_config

        path = (
            load_config().vanilla
            / "localization/simp_chinese/hub_names_l_simp_chinese.yml"
        )
        if not path.is_file():
            raise unittest.SkipTest("vanilla hub names not found")
        names = load_hub_names(path)
        self.assertEqual(names[("STATE_NORTH_RHINE", "city")], "科隆")


if __name__ == "__main__":
    unittest.main()
