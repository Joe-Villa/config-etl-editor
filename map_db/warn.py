"""Collect import warnings and errors."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass
class ImportLog:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors

    def persist(self, conn: sqlite3.Connection) -> None:
        rows = [("error", m) for m in self.errors] + [("warning", m) for m in self.warnings]
        conn.executemany(
            "INSERT INTO import_msg (severity, message) VALUES (?, ?)",
            rows,
        )

    def print_summary(self) -> None:
        if self.warnings:
            print(f"  警告 {len(self.warnings)} 条：")
            for msg in self.warnings[:20]:
                print(f"    - {msg}")
            if len(self.warnings) > 20:
                print(f"    ... 另有 {len(self.warnings) - 20} 条")
        if self.errors:
            print(f"  错误 {len(self.errors)} 条：")
            for msg in self.errors[:20]:
                print(f"    - {msg}")
            if len(self.errors) > 20:
                print(f"    ... 另有 {len(self.errors) - 20} 条")
