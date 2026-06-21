"""Tests for clean province ownership resolution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_db import ProvinceOwner, resolve_clean_province_owners  # noqa: E402
from history_states_flat import StateOwnershipRow  # noqa: E402
from warn import ImportLog  # noqa: E402


class ProvinceOwnershipResolveTest(unittest.TestCase):
    def test_later_claim_wins_on_tag_conflict(self) -> None:
        rows = [
            StateOwnershipRow(
                state="STATE_TEST",
                tag="MEX",
                owned_provinces=["x11111111", "x22222222"],
            ),
            StateOwnershipRow(
                state="STATE_TEST",
                tag="COM",
                owned_provinces=["x11111111"],
            ),
        ]
        log = ImportLog()
        _, owners = resolve_clean_province_owners(
            rows,
            {"x11111111": "STATE_TEST", "x22222222": "STATE_TEST"},
            {"MEX", "COM"},
            {"STATE_TEST"},
            log,
        )
        self.assertEqual(owners["x11111111"], ProvinceOwner("STATE_TEST", "COM"))
        self.assertEqual(owners["x22222222"], ProvinceOwner("STATE_TEST", "MEX"))
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("冲突", log.warnings[0])
        self.assertIn("归属改为 COM", log.warnings[0])

    def test_duplicate_in_same_row_ignored(self) -> None:
        rows = [
            StateOwnershipRow(
                state="STATE_TEST",
                tag="AAA",
                owned_provinces=["x11111111", "x11111111"],
            ),
        ]
        log = ImportLog()
        _, owners = resolve_clean_province_owners(
            rows,
            {"x11111111": "STATE_TEST"},
            {"AAA"},
            {"STATE_TEST"},
            log,
        )
        self.assertEqual(len(owners), 1)
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("重复", log.warnings[0])


class StProvIntegrityTest(unittest.TestCase):
    def test_map_states_mismatch_warns_and_fixes(self) -> None:
        import sqlite3

        from build_db import _validate_st_prov_integrity  # noqa: E402

        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE geo_state (state TEXT PRIMARY KEY);
            CREATE TABLE ref_sr (state TEXT PRIMARY KEY, sr_id INTEGER);
            CREATE TABLE ref_sr_prov (state TEXT, province TEXT PRIMARY KEY);
            CREATE TABLE st (state TEXT, tag TEXT, state_type TEXT, PRIMARY KEY (state, tag));
            CREATE TABLE st_prov (province TEXT PRIMARY KEY, state TEXT, tag TEXT);
            INSERT INTO ref_sr VALUES ('STATE_TOKAI', 1);
            INSERT INTO ref_sr VALUES ('STATE_KANSAI', 2);
            INSERT INTO ref_sr_prov VALUES ('STATE_TOKAI', 'xCCB03E');
            INSERT INTO geo_state VALUES ('STATE_KANSAI');
            INSERT INTO st VALUES ('STATE_KANSAI', 'JAP', 'incorporated');
            INSERT INTO st_prov VALUES ('xCCB03E', 'STATE_KANSAI', 'JAP');
            """
        )
        log = ImportLog()
        _validate_st_prov_integrity(conn, log)
        self.assertEqual(len(log.errors), 0)
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("xCCB03E", log.warnings[0])
        self.assertIn("STATE_KANSAI", log.warnings[0])
        self.assertIn("STATE_TOKAI", log.warnings[0])
        self.assertIn("已按 map_data 改为", log.warnings[0])
        row = conn.execute(
            "SELECT state, tag FROM st_prov WHERE province = 'xCCB03E'"
        ).fetchone()
        self.assertEqual(row, ("STATE_TOKAI", "JAP"))

    def test_history_state_mismatch_warns_and_uses_map_data(self) -> None:
        rows = [
            StateOwnershipRow(
                state="STATE_KANSAI",
                tag="JAP",
                owned_provinces=["xCCB03E"],
            ),
        ]
        log = ImportLog()
        _, owners = resolve_clean_province_owners(
            rows,
            {"xCCB03E": "STATE_TOKAI"},
            {"JAP"},
            {"STATE_KANSAI", "STATE_TOKAI"},
            log,
        )
        self.assertEqual(owners["xCCB03E"], ProvinceOwner("STATE_TOKAI", "JAP"))
        self.assertEqual(len(log.errors), 0)
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("xCCB03E", log.warnings[0])
        self.assertIn("STATE_KANSAI", log.warnings[0])
        self.assertIn("STATE_TOKAI", log.warnings[0])
        self.assertIn("已按 map_data 改为", log.warnings[0])

    def test_unknown_province_in_history_warns_and_ignores(self) -> None:
        rows = [
            StateOwnershipRow(
                state="STATE_GANSU",
                tag="XIB",
                owned_provinces=["xBD5671", "x11111111"],
            ),
        ]
        log = ImportLog()
        _, owners = resolve_clean_province_owners(
            rows,
            {"x11111111": "STATE_GANSU"},
            {"XIB"},
            {"STATE_GANSU"},
            log,
        )
        self.assertEqual(owners, {"x11111111": ProvinceOwner("STATE_GANSU", "XIB")})
        self.assertEqual(len(log.errors), 0)
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("xBD5671", log.warnings[0])
        self.assertIn("已忽略", log.warnings[0])

    def test_unknown_state_in_history_warns_and_skips_row(self) -> None:
        rows = [
            StateOwnershipRow(
                state="STATE_FAKE",
                tag="AAA",
                owned_provinces=["x11111111"],
            ),
        ]
        log = ImportLog()
        st_rows, owners = resolve_clean_province_owners(
            rows,
            {"x11111111": "STATE_FAKE"},
            {"AAA"},
            {"STATE_REAL"},
            log,
        )
        self.assertEqual(st_rows, [])
        self.assertEqual(owners, {})
        self.assertEqual(len(log.errors), 0)
        self.assertEqual(len(log.warnings), 1)
        self.assertIn("STATE_FAKE", log.warnings[0])
        self.assertIn("history 行已忽略", log.warnings[0])

    def test_undefined_tag_in_history_errors_and_skips_row(self) -> None:
        rows = [
            StateOwnershipRow(
                state="STATE_TEST",
                tag="ZZZ",
                owned_provinces=["x11111111"],
            ),
        ]
        log = ImportLog()
        st_rows, owners = resolve_clean_province_owners(
            rows,
            {"x11111111": "STATE_TEST"},
            {"AAA"},
            {"STATE_TEST"},
            log,
        )
        self.assertEqual(st_rows, [])
        self.assertEqual(owners, {})
        self.assertEqual(len(log.errors), 1)
        self.assertIn("ZZZ", log.errors[0])
        self.assertIn("未定义的 tag", log.errors[0])
        self.assertEqual(len(log.warnings), 0)


if __name__ == "__main__":
    unittest.main()
