"""Edit operation log (undo payloads stored in undo_json)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from interactive_map.edit.country_fate import country_fate, has_country_fate


def ensure_edit_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS edit_batch (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS edit_log (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL,
            ord INTEGER NOT NULL,
            op TEXT NOT NULL,
            args_json TEXT NOT NULL,
            undo_json TEXT,
            FOREIGN KEY (batch_id) REFERENCES edit_batch (id)
        );
        """
    )


def active_country_tags(conn: sqlite3.Connection) -> set[str]:
    """Tags that currently own at least one province."""
    return {
        str(row[0])
        for row in conn.execute("SELECT DISTINCT tag FROM st_prov")
    }


def _append_country_fate_summary(
    summary: str,
    destroyed: list[str],
    restored: list[str],
) -> str:
    parts: list[str] = []
    if destroyed:
        parts.append("灭国:" + ",".join(destroyed))
    if restored:
        parts.append("复国:" + ",".join(restored))
    if not parts:
        return summary
    return f"{summary} [{'; '.join(parts)}]"


def _enrich_batch_with_country_fate(
    *,
    summary: str,
    payload: object,
    steps: list[tuple[str, object, object | None]],
) -> tuple[str, object, list[tuple[str, object, object | None]]]:
    if not isinstance(payload, dict) or not has_country_fate(payload):
        return summary, payload, steps

    payload = dict(payload)
    destroyed, restored = country_fate(payload)
    payload["countries_destroyed"] = destroyed
    payload["countries_restored"] = restored

    fate = {
        "countries_destroyed": destroyed,
        "countries_restored": restored,
    }
    steps = list(steps)
    steps.append(("country_fate", fate, None))
    summary = _append_country_fate_summary(summary, destroyed, restored)
    return summary, payload, steps


def write_batch(
    conn: sqlite3.Connection,
    *,
    summary: str,
    payload: object,
    steps: list[tuple[str, object, object | None]],
) -> int:
    ensure_edit_schema(conn)
    summary, payload, steps = _enrich_batch_with_country_fate(
        summary=summary,
        payload=payload,
        steps=steps,
    )
    cur = conn.execute(
        "INSERT INTO edit_batch (created_at, summary, payload) VALUES (?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(),
            summary,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    batch_id = int(cur.lastrowid)
    for ord_, (op, args, undo) in enumerate(steps):
        conn.execute(
            """
            INSERT INTO edit_log (batch_id, ord, op, args_json, undo_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                ord_,
                op,
                json.dumps(args, ensure_ascii=False, separators=(",", ":")),
                None
                if undo is None
                else json.dumps(undo, ensure_ascii=False, separators=(",", ":")),
            ),
        )
    return batch_id


def export_edit_log(conn: sqlite3.Connection) -> dict:
    """Export all edit batches and steps for download / undo replay."""
    ensure_edit_schema(conn)
    batches: list[dict] = []
    for batch_id, created_at, summary, payload in conn.execute(
        """
        SELECT id, created_at, summary, payload
        FROM edit_batch
        ORDER BY id
        """
    ):
        steps: list[dict] = []
        for ord_, op, args_json, undo_json in conn.execute(
            """
            SELECT ord, op, args_json, undo_json
            FROM edit_log
            WHERE batch_id = ?
            ORDER BY ord
            """,
            (int(batch_id),),
        ):
            steps.append(
                {
                    "ord": int(ord_),
                    "op": str(op),
                    "args": json.loads(args_json),
                    "undo": None
                    if undo_json is None
                    else json.loads(undo_json),
                }
            )
        batches.append(
            {
                "id": int(batch_id),
                "created_at": str(created_at),
                "summary": str(summary),
                "payload": json.loads(payload),
                "steps": steps,
            }
        )
    return {"batch_count": len(batches), "batches": batches}
