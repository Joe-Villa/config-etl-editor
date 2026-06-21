"""SQLite transaction helpers for multi-step map edits."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager

EDIT_ISOLATION = "DEFERRED"

_ST_PROV_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_st_prov_tag_state ON st_prov (tag, state)",
    "CREATE INDEX IF NOT EXISTS idx_st_prov_state_tag ON st_prov (state, tag)",
)


def configure_edit_connection(conn: sqlite3.Connection) -> None:
    """Use explicit transactions; caller commits on success."""
    conn.isolation_level = EDIT_ISOLATION
    for ddl in _ST_PROV_INDEXES:
        conn.execute(ddl)


@contextmanager
def atomic_edit(conn: sqlite3.Connection):
    """Rollback every change in this block if any step raises."""
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
