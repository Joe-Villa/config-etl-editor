"""Ensure integration test sqlite matches current schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_DB = ROOT / "output" / "test_map_editor.sqlite"

_REQUIRED_RELIGION_COLUMNS = frozenset({"r", "g", "b", "name_zh", "name_en"})


def ensure_test_map_db() -> Path:
    if TEST_DB.is_file():
        conn = sqlite3.connect(TEST_DB)
        try:
            cols = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(ref_religion)")
            }
            if _REQUIRED_RELIGION_COLUMNS.issubset(cols):
                return TEST_DB
        finally:
            conn.close()
        TEST_DB.unlink()

    src = ROOT / "map_db"
    import sys

    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from build_db import build_map_db  # noqa: WPS433
    from editor_config import load_config  # noqa: WPS433

    build_map_db(load_config().vanilla, TEST_DB, load_config(), fail_on_error=True)
    return TEST_DB
