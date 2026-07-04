from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from state_region_flat import (  # noqa: E402
    FlatStateRegion,
    build_province_state_index,
    validate_mod_map_data_state_regions,
)


def _row(state: str, provinces: str, row_id: int = 1) -> FlatStateRegion:
    return FlatStateRegion(
        id=row_id,
        state=state,
        coastal=False,
        provinces=provinces,
        prime_land="",
        impassable="",
        arable_land=0,
        arable_resources="",
    )


class ProvinceStateIndexTest(unittest.TestCase):
    def test_duplicate_in_same_state_warns(self) -> None:
        rows = [_row("STATE_A", "x11111111,x11111111,x22222222")]
        warnings: list[str] = []
        log = type(
            "L",
            (),
            {"warn": lambda _s, m: warnings.append(m), "error": lambda _s, m: None},
        )()
        index = build_province_state_index(rows, log)
        self.assertEqual(index.province_to_state["x11111111"], "STATE_A")
        self.assertEqual(len(index.province_to_state), 2)
        self.assertEqual(len(warnings), 1)
        self.assertIn("重复", warnings[0])

    def test_cross_state_resolved_by_authority(self) -> None:
        rows = [
            _row("STATE_A", "x11111111", 1),
            _row("STATE_B", "x11111111", 2),
        ]
        warnings: list[str] = []
        errors: list[str] = []
        log = type(
            "L",
            (),
            {
                "warn": lambda _s, m: warnings.append(m),
                "error": lambda _s, m: errors.append(m),
            },
        )()
        index = build_province_state_index(
            rows,
            log,
            authority={"x11111111": "STATE_B"},
        )
        self.assertEqual(index.province_to_state["x11111111"], "STATE_B")
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("STATE_A 不应该拥有", warnings[0])

    def test_cross_state_fallback_prefers_mod_state(self) -> None:
        rows = [
            _row("STATE_A", "x11111111", 1),
            _row("STATE_B", "x11111111", 2),
        ]
        warnings: list[str] = []
        log = type(
            "L",
            (),
            {"warn": lambda _s, m: warnings.append(m), "error": lambda _s, m: None},
        )()
        index = build_province_state_index(
            rows,
            log,
            mod_states=frozenset({"STATE_B"}),
        )
        self.assertEqual(index.province_to_state["x11111111"], "STATE_B")
        self.assertTrue(any("STATE_A 不应该拥有" in w for w in warnings))

    def test_strict_mod_map_data_errors_on_internal_duplicate(self) -> None:
        mod = Path(self.temp_dir) / "mod"
        vanilla = Path(self.temp_dir) / "vanilla"
        (mod / "map_data" / "state_regions").mkdir(parents=True)
        (vanilla / "map_data" / "state_regions").mkdir(parents=True)
        (mod / "map_data" / "state_regions" / "01_test.txt").write_text(
            """
STATE_A = {
    id = 1
    provinces = { "x11111111" }
}
STATE_B = {
    id = 2
    provinces = { "x11111111" }
}
""",
            encoding="utf-8",
        )
        errors: list[str] = []
        log = type(
            "L",
            (),
            {"warn": lambda _s, m: None, "error": lambda _s, m: errors.append(m)},
        )()
        validate_mod_map_data_state_regions(mod, vanilla, frozenset(), log)
        self.assertEqual(len(errors), 1)
        self.assertIn("map_data 严重错误", errors[0])

    def setUp(self) -> None:
        import tempfile

        self.temp_dir = tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
