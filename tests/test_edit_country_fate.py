"""Tests for country destroyed/restored logging in edit batches."""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.atomic import configure_edit_connection  # noqa: E402
from interactive_map.edit.country_homeland_macro import release_country  # noqa: E402
from interactive_map.edit.log import export_edit_log  # noqa: E402
from interactive_map.edit.pops import add_pop  # noqa: E402
from interactive_map.edit.transfer import (  # noqa: E402
    change_tag,
    expand_scope_to_full_state,
)
from tests.test_country_homeland_macro import _homeland_macro_conn  # noqa: E402
from tests.test_edit_transfer import _minimal_transfer_conn  # noqa: E402


def _latest_batch(conn: sqlite3.Connection) -> dict:
    payload = export_edit_log(conn)
    batches = payload["batches"]
    if not batches:
        raise AssertionError("no edit batches recorded")
    return batches[-1]


class EditCountryFateTest(unittest.TestCase):
    def test_expand_logs_annexed_country_as_destroyed(self) -> None:
        conn = _minimal_transfer_conn()
        configure_edit_connection(conn)
        try:
            expand_scope_to_full_state(conn, tag="AAA", state="STATE_TEST")
            batch = _latest_batch(conn)
            self.assertEqual(batch["payload"]["countries_destroyed"], ["BBB"])
            self.assertEqual(batch["payload"]["countries_restored"], [])
            self.assertIn("灭国:BBB", batch["summary"])
            fate_steps = [s for s in batch["steps"] if s["op"] == "country_fate"]
            self.assertEqual(len(fate_steps), 1)
            self.assertEqual(
                fate_steps[0]["args"],
                {
                    "countries_destroyed": ["BBB"],
                    "countries_restored": [],
                },
            )
        finally:
            conn.close()

    def test_release_logs_restored_country(self) -> None:
        conn = _homeland_macro_conn()
        try:
            release_country(conn, tag="AAA", target_tag="GBR")
            batch = _latest_batch(conn)
            self.assertEqual(batch["payload"]["countries_restored"], ["GBR"])
            self.assertEqual(batch["payload"]["countries_destroyed"], [])
            self.assertIn("复国:GBR", batch["summary"])
        finally:
            conn.close()

    def test_release_annihilate_logs_destroyed_releaser(self) -> None:
        conn = _homeland_macro_conn()
        try:
            conn.execute("DELETE FROM st_prov WHERE tag = 'AAA' AND state = 'STATE_IND'")
            conn.execute("DELETE FROM st WHERE tag = 'AAA' AND state = 'STATE_IND'")
            release_country(conn, tag="AAA", target_tag="GBR")
            batch = _latest_batch(conn)
            self.assertEqual(batch["payload"]["countries_destroyed"], ["AAA"])
            self.assertEqual(batch["payload"]["countries_restored"], ["GBR"])
        finally:
            conn.close()

    def test_change_tag_logs_destroyed_and_restored(self) -> None:
        conn = _minimal_transfer_conn()
        configure_edit_connection(conn)
        try:
            change_tag(conn, old_tag="AAA", new_tag="CCC")
            batch = _latest_batch(conn)
            self.assertEqual(batch["payload"]["countries_destroyed"], ["AAA"])
            self.assertEqual(batch["payload"]["countries_restored"], ["CCC"])
            self.assertIn("灭国:AAA", batch["summary"])
            self.assertIn("复国:CCC", batch["summary"])
            fate_steps = [s for s in batch["steps"] if s["op"] == "country_fate"]
            self.assertEqual(len(fate_steps), 1)
        finally:
            conn.close()

    def test_scope_edit_without_atomic_edit_skips_fate_fields(self) -> None:
        conn = _minimal_transfer_conn()
        try:
            add_pop(
                conn,
                tag="AAA",
                state="STATE_TEST",
                culture="british",
                religion=None,
                is_slaves=False,
                size=1000,
            )
            batch = _latest_batch(conn)
            self.assertNotIn("countries_destroyed", batch["payload"])
            self.assertNotIn("countries_restored", batch["payload"])
        finally:
            conn.close()

if __name__ == "__main__":
    unittest.main()
