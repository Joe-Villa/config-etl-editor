"""Database constraints for st_bld_own.level."""

from __future__ import annotations

import sqlite3
import unittest


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE st_bld (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL,
            tag TEXT NOT NULL,
            building TEXT NOT NULL,
            reserves INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE st_bld_own (
            bld_id INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            ownership TEXT NOT NULL,
            level INTEGER NOT NULL CHECK (level >= 1),
            owner_tag TEXT NOT NULL DEFAULT '',
            owner_state TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (bld_id, ord),
            FOREIGN KEY (bld_id) REFERENCES st_bld (id) ON DELETE CASCADE
        ) STRICT;

        INSERT INTO st_bld (id, state, tag, building, reserves)
        VALUES (1, 'STATE_TEST', 'TAG', 'building_test', 1);
        """
    )
    return conn


class BuildingLevelConstraintTest(unittest.TestCase):
    def test_accepts_positive_integer(self) -> None:
        conn = _open_db()
        conn.execute(
            """
            INSERT INTO st_bld_own (bld_id, ord, ownership, level)
            VALUES (1, 0, 'country', 1)
            """
        )
        conn.commit()
        conn.close()

    def test_rejects_zero(self) -> None:
        conn = _open_db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO st_bld_own (bld_id, ord, ownership, level)
                VALUES (1, 0, 'country', 0)
                """
            )
        conn.close()

    def test_rejects_negative(self) -> None:
        conn = _open_db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO st_bld_own (bld_id, ord, ownership, level)
                VALUES (1, 0, 'country', -3)
                """
            )
        conn.close()

    def test_rejects_fractional_value(self) -> None:
        conn = _open_db()
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO st_bld_own (bld_id, ord, ownership, level)
                VALUES (1, 0, 'country', 2.5)
                """
            )
        conn.close()


if __name__ == "__main__":
    unittest.main()
