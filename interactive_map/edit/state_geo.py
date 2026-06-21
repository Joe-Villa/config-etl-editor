"""Geographic state attributes: incorporation, homelands, claims."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from interactive_map.macro_edit_job import make_loop_progress
from interactive_map.edit.log import write_batch
from interactive_map.edit.snapshot import (
    capture_incorporate_all_undo,
    capture_toggle_undo,
)
from interactive_map.edit.atomic import atomic_edit

STATE_TYPES = ("incorporated", "unincorporated")
STATE_TYPE_LABELS = {
    "incorporated": "已整合",
    "unincorporated": "未整合",
}


def _require_scope(conn: sqlite3.Connection, tag: str, state: str) -> str:
    row = conn.execute(
        "SELECT state_type FROM st WHERE tag = ? AND state = ?",
        (tag, state),
    ).fetchone()
    if row is None:
        raise ValueError(f"scope state 不存在：{tag}/{state}")
    return str(row[0])


def _ensure_geo_state(conn: sqlite3.Connection, state: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM ref_sr WHERE state = ?", (state,)
    ).fetchone()
    if row is None:
        raise ValueError(f"未知地区：{state}")
    conn.execute("INSERT OR IGNORE INTO geo_state (state) VALUES (?)", (state,))


def _validate_state_type(state_type: str) -> str:
    value = str(state_type).strip()
    if value not in STATE_TYPES:
        raise ValueError(f"state_type 必须是 {' / '.join(STATE_TYPES)}")
    return value


def _validate_culture(conn: sqlite3.Connection, culture: str) -> str:
    value = str(culture).strip()
    if not value:
        raise ValueError("需要 culture")
    row = conn.execute(
        "SELECT 1 FROM ref_culture WHERE culture = ?", (value,)
    ).fetchone()
    if row is None:
        raise ValueError(f"未知文化：{value}")
    return value


def _validate_claim_tag(conn: sqlite3.Connection, claim_tag: str) -> str:
    """Claim tags must be in ref_tag whitelist; active ownership is not required."""
    value = str(claim_tag).strip()
    if not value:
        raise ValueError("需要 claim_tag")
    row = conn.execute("SELECT 1 FROM ref_tag WHERE tag = ?", (value,)).fetchone()
    if row is None:
        raise ValueError(f"未知 claim tag：{value}")
    return value


def _normalize_action(action: str) -> str:
    value = str(action).strip().lower()
    if value not in ("add", "remove"):
        raise ValueError("action 必须是 add 或 remove")
    return value


def load_state_geo_options(conn: sqlite3.Connection, tag: str, state: str) -> dict:
    _require_scope(conn, tag, state)
    cultures = [
        str(row[0])
        for row in conn.execute("SELECT culture FROM ref_culture ORDER BY culture")
    ]
    claim_tags = [
        str(row[0])
        for row in conn.execute("SELECT tag FROM ref_tag ORDER BY tag")
    ]
    homelands = [
        str(row[0])
        for row in conn.execute(
            "SELECT culture FROM geo_homeland WHERE state = ? ORDER BY culture",
            (state,),
        )
    ]
    claims = [
        str(row[0])
        for row in conn.execute(
            "SELECT claim_tag FROM geo_claim WHERE state = ? ORDER BY claim_tag",
            (state,),
        )
    ]
    state_type = _require_scope(conn, tag, state)
    return {
        "tag": tag,
        "state": state,
        "state_type": state_type,
        "homelands": homelands,
        "claims": claims,
        "cultures": cultures,
        "claim_tags": claim_tags,
        "state_types": [
            {"value": value, "label": STATE_TYPE_LABELS[value]} for value in STATE_TYPES
        ],
    }


def change_state_type(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    state_type: str,
) -> dict:
    before = _require_scope(conn, tag, state)
    new_type = _validate_state_type(state_type)
    if before == new_type:
        raise ValueError("整合状态未变化")
    conn.execute(
        "UPDATE st SET state_type = ? WHERE tag = ? AND state = ?",
        (new_type, tag, state),
    )
    result = {
        "op": "change_state_type",
        "tag": tag,
        "state": state,
        "before": before,
        "after": new_type,
    }
    batch_id = write_batch(
        conn,
        summary=f"change_state_type {tag}/{state} {before}->{new_type}",
        payload=result,
        steps=[("change_state_type", result, {"before": before})],
    )
    result["batch_id"] = batch_id
    return result


def incorporate_all_states(
    conn: sqlite3.Connection,
    *,
    tag: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Set every scope state owned by ``tag`` to incorporated."""
    with atomic_edit(conn):
        tag = str(tag)
        rows = conn.execute(
            "SELECT state, state_type FROM st WHERE tag = ? ORDER BY state",
            (tag,),
        ).fetchall()
        if not rows:
            raise ValueError(f"{tag} 没有任何 scope state")

        updated: list[str] = []
        candidates = [
            (str(state), str(state_type))
            for state, state_type in rows
            if str(state_type) != "incorporated"
        ]
        tick = make_loop_progress(on_progress, len(candidates), prefix="设为已整合 ")
        for state, state_type in rows:
            state = str(state)
            if str(state_type) != "incorporated":
                conn.execute(
                    "UPDATE st SET state_type = 'incorporated' WHERE tag = ? AND state = ?",
                    (tag, state),
                )
                updated.append(state)
                tick(f"正在设为已整合 {state}")

        if not updated:
            raise ValueError(f"{tag} 所有地区已是已整合")

        result = {
            "op": "incorporate_all_states",
            "tag": tag,
            "states_updated": updated,
            "scope_count": len(updated),
        }
        undo = capture_incorporate_all_undo(conn, tag=tag, states=rows)
        batch_id = write_batch(
            conn,
            summary=f"incorporate_all_states {tag} ({len(updated)} scopes)",
            payload=result,
            steps=[("incorporate_all_states", result, undo)],
        )
        result["batch_id"] = batch_id
        return result


def change_homeland(
    conn: sqlite3.Connection,
    *,
    state: str,
    culture: str,
    action: str,
) -> dict:
    state = str(state)
    culture = _validate_culture(conn, culture)
    op = _normalize_action(action)
    _ensure_geo_state(conn, state)

    exists = conn.execute(
        "SELECT 1 FROM geo_homeland WHERE state = ? AND culture = ?",
        (state, culture),
    ).fetchone()

    if op == "add":
        if exists is not None:
            raise ValueError(f"文化本土已存在：{culture}")
        conn.execute(
            "INSERT INTO geo_homeland (state, culture) VALUES (?, ?)",
            (state, culture),
        )
    else:
        if exists is None:
            raise ValueError(f"文化本土不存在：{culture}")
        conn.execute(
            "DELETE FROM geo_homeland WHERE state = ? AND culture = ?",
            (state, culture),
        )

    homelands = [
        str(row[0])
        for row in conn.execute(
            "SELECT culture FROM geo_homeland WHERE state = ? ORDER BY culture",
            (state,),
        )
    ]
    result = {
        "op": "change_homeland",
        "state": state,
        "culture": culture,
        "action": op,
        "homelands": homelands,
    }
    undo = capture_toggle_undo(
        kind="change_homeland",
        state=state,
        key=culture,
        key_name="culture",
        action=op,
    )
    batch_id = write_batch(
        conn,
        summary=f"change_homeland {state} {culture} {op}",
        payload=result,
        steps=[("change_homeland", result, undo)],
    )
    result["batch_id"] = batch_id
    return result


def change_claim(
    conn: sqlite3.Connection,
    *,
    state: str,
    claim_tag: str,
    action: str,
) -> dict:
    state = str(state)
    claim_tag = _validate_claim_tag(conn, claim_tag)
    op = _normalize_action(action)
    _ensure_geo_state(conn, state)

    exists = conn.execute(
        "SELECT 1 FROM geo_claim WHERE state = ? AND claim_tag = ?",
        (state, claim_tag),
    ).fetchone()

    if op == "add":
        if exists is not None:
            raise ValueError(f"宣称已存在：{claim_tag}")
        conn.execute(
            "INSERT INTO geo_claim (state, claim_tag) VALUES (?, ?)",
            (state, claim_tag),
        )
    else:
        if exists is None:
            raise ValueError(f"宣称不存在：{claim_tag}")
        conn.execute(
            "DELETE FROM geo_claim WHERE state = ? AND claim_tag = ?",
            (state, claim_tag),
        )

    claims = [
        str(row[0])
        for row in conn.execute(
            "SELECT claim_tag FROM geo_claim WHERE state = ? ORDER BY claim_tag",
            (state,),
        )
    ]
    result = {
        "op": "change_claim",
        "state": state,
        "claim_tag": claim_tag,
        "action": op,
        "claims": claims,
    }
    undo = capture_toggle_undo(
        kind="change_claim",
        state=state,
        key=claim_tag,
        key_name="claim_tag",
        action=op,
    )
    batch_id = write_batch(
        conn,
        summary=f"change_claim {state} {claim_tag} {op}",
        payload=result,
        steps=[("change_claim", result, undo)],
    )
    result["batch_id"] = batch_id
    return result
