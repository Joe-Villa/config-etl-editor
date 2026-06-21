"""Tests for duplicate homeland/claim handling during import."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_db import build_map_db  # noqa: E402
from editor_config import load_config  # noqa: E402
from warn import ImportLog  # noqa: E402


class DuplicateClaimTest(unittest.TestCase):
    def test_duplicate_claim_insert_logic(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE geo_state (state TEXT PRIMARY KEY);
            CREATE TABLE geo_claim (
                state TEXT NOT NULL,
                claim_tag TEXT NOT NULL,
                PRIMARY KEY (state, claim_tag)
            );
            """
        )
        conn.execute("INSERT INTO geo_state (state) VALUES ('STATE_TEST')")
        log = ImportLog()
        claims = ["IEM", "IEM"]
        seen_claims: set[str] = set()
        for claim in claims:
            if claim in seen_claims:
                log.warn(f"STATE_TEST claim {claim}：重复，已忽略")
                continue
            seen_claims.add(claim)
            conn.execute(
                "INSERT INTO geo_claim (state, claim_tag) VALUES (?, ?)",
                ("STATE_TEST", claim),
            )

        self.assertTrue(log.ok)
        self.assertEqual(len(log.warnings), 1)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM geo_claim").fetchone()[0],
            1,
        )
        conn.close()

    def test_workshop_mod_with_duplicate_claims_builds(self) -> None:
        mod = Path(
            "/home/liulingda/.steam/debian-installation/steamapps/workshop/content/529340/3260268786"
        )
        if not mod.is_dir():
            self.skipTest("workshop mod 3260268786 不在本机")

        out = Path(tempfile.mktemp(suffix=".sqlite"))
        try:
            log = build_map_db(mod, out, load_config(), fail_on_error=False)
            dup_warnings = [
                msg for msg in log.warnings if "claim" in msg and "重复" in msg
            ]
            self.assertGreaterEqual(len(dup_warnings), 2)
            self.assertEqual(
                dup_warnings[0],
                "STATE_ARAUCANIA claim IEM：重复，已忽略",
            )
        finally:
            if out.is_file():
                out.unlink()


if __name__ == "__main__":
    unittest.main()
