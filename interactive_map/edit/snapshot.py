"""Capture logical DB state for edit undo (row ids may differ after restore)."""

from __future__ import annotations

import sqlite3

from interactive_map.edit.buildings import resolve_owner_tag_for_export


def _load_building_snapshot(conn: sqlite3.Connection, bld_id: int) -> dict:
    row = conn.execute(
        "SELECT id, state, tag, building, reserves FROM st_bld WHERE id = ?",
        (bld_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"建筑 id={bld_id} 不存在")
    bld_id, state, tag, building, reserves = row
    ownerships = [
        {
            "ownership": str(ownership),
            "level": int(level),
            "owner_tag": str(owner_tag),
            "owner_state": str(owner_state),
        }
        for ownership, level, owner_tag, owner_state in conn.execute(
            """
            SELECT ownership, level, owner_tag, owner_state
            FROM st_bld_own WHERE bld_id = ? ORDER BY ord
            """,
            (bld_id,),
        )
    ]
    pms = [
        str(pm)
        for (pm,) in conn.execute(
            "SELECT pm FROM st_bld_pm WHERE bld_id = ? ORDER BY ord", (bld_id,)
        )
    ]
    return {
        "id": int(bld_id),
        "state": str(state),
        "tag": str(tag),
        "building": str(building),
        "reserves": int(reserves),
        "ownerships": ownerships,
        "pms": pms,
    }


def _load_pop_snapshot(conn: sqlite3.Connection, pop_id: int) -> dict:
    row = conn.execute(
        """
        SELECT id, state, tag, culture, religion, is_slaves, size
        FROM st_pop WHERE id = ?
        """,
        (pop_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"人口条目不存在：id={pop_id}")
    pop_id, state, tag, culture, religion, is_slaves, size = row
    return {
        "id": int(pop_id),
        "state": str(state),
        "tag": str(tag),
        "culture": str(culture),
        "religion": str(religion) if religion is not None else None,
        "is_slaves": bool(is_slaves),
        "size": int(size),
    }


def capture_scope_meta(
    conn: sqlite3.Connection, state: str, tag: str
) -> dict[str, object]:
    row = conn.execute(
        "SELECT state_type FROM st WHERE state = ? AND tag = ?",
        (state, tag),
    ).fetchone()
    return {
        "state": state,
        "tag": tag,
        "exists": row is not None,
        "state_type": str(row[0]) if row is not None else None,
    }


def capture_geo_state_snapshot(conn: sqlite3.Connection, state: str) -> dict:
    """Logical snapshot of one geographic state (all tags)."""
    state = str(state)
    provinces = [
        {"province": str(province), "tag": str(tag)}
        for province, tag in conn.execute(
            """
            SELECT province, tag FROM st_prov
            WHERE state = ?
            ORDER BY province
            """,
            (state,),
        )
    ]
    scopes = [
        {"tag": str(tag), "state_type": str(state_type)}
        for tag, state_type in conn.execute(
            """
            SELECT tag, state_type FROM st
            WHERE state = ?
            ORDER BY tag
            """,
            (state,),
        )
    ]
    pop_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM st_pop WHERE state = ? ORDER BY id", (state,)
        )
    ]
    bld_ids = [
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM st_bld WHERE state = ? ORDER BY id", (state,)
        )
    ]
    return {
        "state": state,
        "provinces": provinces,
        "scopes": scopes,
        "pops": [_load_pop_snapshot(conn, pop_id) for pop_id in pop_ids],
        "buildings": [_load_building_snapshot(conn, bld_id) for bld_id in bld_ids],
    }


def capture_foreign_ownership_for_effective_owner(
    conn: sqlite3.Connection, owner_tag: str
) -> list[dict]:
    """``st_bld_own`` rows whose effective owner equals ``owner_tag``."""
    owner_tag = str(owner_tag)
    rows: list[dict] = []
    for bld_id, scope_tag in conn.execute(
        "SELECT id, tag FROM st_bld ORDER BY id",
    ):
        bld_id = int(bld_id)
        scope_tag = str(scope_tag)
        for ord_, stored_owner in conn.execute(
            """
            SELECT ord, owner_tag
            FROM st_bld_own
            WHERE bld_id = ?
            ORDER BY ord
            """,
            (bld_id,),
        ):
            effective = resolve_owner_tag_for_export(scope_tag, str(stored_owner))
            if effective != owner_tag:
                continue
            rows.append(
                {
                    "bld_id": bld_id,
                    "ord": int(ord_),
                    "owner_tag": str(stored_owner),
                }
            )
    return rows


def foreign_ownership_undo(owner_tag: str, rows: list[dict]) -> dict:
    return {"owner_tag": str(owner_tag), "rows": rows}


def capture_set_owner_undo(
    conn: sqlite3.Connection,
    *,
    province: str,
    state: str,
    from_tag: str,
    to_tag: str,
) -> dict:
    return {
        "kind": "set_owner",
        "province": str(province),
        "state": str(state),
        "from_tag": str(from_tag),
        "to_tag": str(to_tag),
        "from_scope": capture_scope_meta(conn, state, from_tag),
        "to_scope": capture_scope_meta(conn, state, to_tag),
    }


def capture_transfer_undo(
    conn: sqlite3.Connection,
    *,
    state: str,
    origin_tag: str,
    capture_foreign_for: str | None = None,
) -> dict:
    undo: dict[str, object] = {
        "kind": "transfer",
        "state": str(state),
        "origin_tag": str(origin_tag),
        "geo_state": capture_geo_state_snapshot(conn, state),
    }
    if capture_foreign_for is not None:
        rows = capture_foreign_ownership_for_effective_owner(conn, capture_foreign_for)
        undo["foreign_ownership"] = foreign_ownership_undo(capture_foreign_for, rows)
    return undo


def capture_change_tag_undo(
    conn: sqlite3.Connection, *, old_tag: str, new_tag: str
) -> dict:
    old_tag = str(old_tag)
    scopes = [
        {"state": str(state), "state_type": str(state_type)}
        for state, state_type in conn.execute(
            """
            SELECT state, state_type FROM st
            WHERE tag = ?
            ORDER BY state
            """,
            (old_tag,),
        )
    ]
    return {
        "kind": "change_tag",
        "from_tag": old_tag,
        "to_tag": str(new_tag),
        "scopes": scopes,
        "foreign_ownership": foreign_ownership_undo(
            old_tag,
            capture_foreign_ownership_for_effective_owner(conn, old_tag),
        ),
    }


def capture_incorporate_all_undo(
    conn: sqlite3.Connection, *, tag: str, states: list[tuple[str, str]]
) -> dict:
    return {
        "kind": "incorporate_all_states",
        "tag": str(tag),
        "scopes": [
            {"state": str(state), "state_type": str(state_type)}
            for state, state_type in states
            if str(state_type) != "incorporated"
        ],
    }


def capture_toggle_undo(
    *,
    kind: str,
    state: str,
    key: str,
    key_name: str,
    action: str,
) -> dict:
    inverse = "remove" if action == "add" else "add"
    return {
        "kind": kind,
        "state": str(state),
        key_name: str(key),
        "action": inverse,
    }
