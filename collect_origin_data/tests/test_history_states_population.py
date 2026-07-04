from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from history_pops_flat import PopByTagRow  # noqa: E402
from history_states_flat import (  # noqa: E402
    StateOwnershipRow,
    merge_population_into_ownership,
)


class HistoryStatesPopulationTests(unittest.TestCase):
    def test_merge_population_defaults_to_zero(self) -> None:
        ownership = [
            StateOwnershipRow(state="STATE_A", tag="GBR"),
            StateOwnershipRow(state="STATE_B", tag="FRA"),
        ]
        pops = [
            PopByTagRow(state="STATE_A", tag="GBR", population=12345),
            PopByTagRow(state="STATE_ORPHAN", tag="ZZZ", population=999),
        ]
        merged = merge_population_into_ownership(ownership, pops)
        self.assertEqual(merged[0].population, 12345)
        self.assertEqual(merged[1].population, 0)

    def test_merge_population_matches_state_and_tag(self) -> None:
        ownership = [StateOwnershipRow(state="STATE_A", tag="GBR")]
        pops = [PopByTagRow(state="STATE_A", tag="FRA", population=100)]
        merged = merge_population_into_ownership(ownership, pops)
        self.assertEqual(merged[0].population, 0)


if __name__ == "__main__":
    unittest.main()
