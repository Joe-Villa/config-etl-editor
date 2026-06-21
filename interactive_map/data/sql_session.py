"""Thin sqlite wrapper — data layer executes SQL and returns rows."""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable


class SqlSession:
    """Read-only facade over a sqlite connection for repository code."""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, tuple(params))

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[tuple]:
        return list(self.execute(sql, params).fetchall())

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> tuple | None:
        return self.execute(sql, params).fetchone()
