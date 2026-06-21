"""Province / state / country transfer with cascading data consistency.

Homelands (``geo_homeland``) and claims (``geo_claim``) are geographic-state
attributes and are never modified here — including when a tag is annexed or
ceases to hold any provinces.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from interactive_map.macro_edit_job import make_loop_progress

from interactive_map.edit.buildings import resolve_owner_tag_for_export
from interactive_map.edit.country_fate import (
    note_annexed_tags,
    note_country_destroyed,
    note_country_restored,
)
from interactive_map.edit.log import write_batch
from interactive_map.edit.atomic import atomic_edit
from interactive_map.edit.snapshot import (
    capture_change_tag_undo,
    capture_foreign_ownership_for_effective_owner,
    capture_geo_state_snapshot,
    capture_set_owner_undo,
    capture_transfer_undo,
    foreign_ownership_undo,
)
from interactive_map.png_util import normalize_province_db, province_db_to_hex


def normalize_province_hex(hex_str: str) -> str:
    """Return province as canonical DB key ``xRRGGBB``."""
    return normalize_province_db(hex_str)


def find_province_owner(conn: sqlite3.Connection, province: str) -> tuple[str, str]:
    """Return ``(state, tag)`` for an owned province."""
    province = normalize_province_hex(province)
    row = conn.execute(
        "SELECT state, tag FROM st_prov WHERE province = ?",
        (province,),
    ).fetchone()
    if row is None:
        raise ValueError(f"地块未被任何国家拥有：{province}")
    return str(row[0]), str(row[1])


def count_provinces_in_scope(conn: sqlite3.Connection, state: str, tag: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM st_prov WHERE state = ? AND tag = ?",
        (state, tag),
    ).fetchone()
    return int(row[0]) if row else 0


def tag_has_provinces(conn: sqlite3.Connection, tag: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM st_prov WHERE tag = ? LIMIT 1",
        (tag,),
    ).fetchone()
    return row is not None


def primary_cultures(conn: sqlite3.Connection, tag: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT culture FROM ref_tag_culture WHERE tag = ? ORDER BY ord, culture",
            (str(tag),),
        )
    ]


def _validate_tag(conn: sqlite3.Connection, tag: str) -> None:
    row = conn.execute("SELECT 1 FROM ref_tag WHERE tag = ?", (tag,)).fetchone()
    if row is None:
        raise ValueError(f"未知国家 tag：{tag}")


def _scope_state_type(conn: sqlite3.Connection, state: str, tag: str) -> str | None:
    row = conn.execute(
        "SELECT state_type FROM st WHERE state = ? AND tag = ?",
        (state, tag),
    ).fetchone()
    return str(row[0]) if row else None


def _ensure_st_scope(
    conn: sqlite3.Connection,
    state: str,
    tag: str,
    *,
    state_type: str = "unincorporated",
) -> bool:
    """Ensure ``st`` row exists; return True if newly created."""
    row = conn.execute(
        "SELECT state_type FROM st WHERE state = ? AND tag = ?",
        (state, tag),
    ).fetchone()
    if row is not None:
        return False
    geo = conn.execute(
        "SELECT 1 FROM geo_state WHERE state = ?", (state,)
    ).fetchone()
    if geo is None:
        conn.execute("INSERT INTO geo_state (state) VALUES (?)", (state,))
    conn.execute(
        "INSERT INTO st (state, tag, state_type) VALUES (?, ?, ?)",
        (state, tag, state_type),
    )
    return True


def _delete_st_scope_if_empty(conn: sqlite3.Connection, state: str, tag: str) -> bool:
    """Delete ``st`` row when it has no provinces, pops, or buildings."""
    if count_provinces_in_scope(conn, state, tag) > 0:
        return False
    pop_row = conn.execute(
        "SELECT 1 FROM st_pop WHERE state = ? AND tag = ? LIMIT 1",
        (state, tag),
    ).fetchone()
    if pop_row is not None:
        return False
    bld_row = conn.execute(
        "SELECT 1 FROM st_bld WHERE state = ? AND tag = ? LIMIT 1",
        (state, tag),
    ).fetchone()
    if bld_row is not None:
        return False
    conn.execute("DELETE FROM st WHERE state = ? AND tag = ?", (state, tag))
    return True


def _resolve_target_state_type(
    conn: sqlite3.Connection,
    state: str,
    origin_tag: str,
    new_tag: str,
    state_type: str | None,
) -> str:
    if state_type is not None:
        return state_type
    existing = _scope_state_type(conn, state, new_tag)
    if existing is not None:
        return existing
    origin_type = _scope_state_type(conn, state, origin_tag)
    return origin_type or "unincorporated"


def _apply_target_state_type(
    conn: sqlite3.Connection,
    state: str,
    tag: str,
    state_type: str,
) -> None:
    conn.execute(
        "UPDATE st SET state_type = ? WHERE state = ? AND tag = ?",
        (state_type, state, tag),
    )


def _merge_pops(
    conn: sqlite3.Connection,
    state: str,
    from_tag: str,
    to_tag: str,
) -> dict[str, int]:
    moved = 0
    merged = 0
    for pop_id, culture, religion, is_slaves, size in conn.execute(
        """
        SELECT id, culture, religion, is_slaves, size
        FROM st_pop
        WHERE state = ? AND tag = ?
        ORDER BY id
        """,
        (state, from_tag),
    ):
        existing = conn.execute(
            """
            SELECT id, size FROM st_pop
            WHERE state = ? AND tag = ? AND culture = ?
              AND IFNULL(religion, '') = IFNULL(?, '')
              AND is_slaves = ?
            """,
            (state, to_tag, culture, religion, int(is_slaves)),
        ).fetchone()
        if existing is None:
            conn.execute(
                "UPDATE st_pop SET tag = ? WHERE id = ?",
                (to_tag, int(pop_id)),
            )
            moved += 1
            continue
        target_id, target_size = existing
        conn.execute(
            "UPDATE st_pop SET size = ? WHERE id = ?",
            (int(target_size) + int(size), int(target_id)),
        )
        conn.execute("DELETE FROM st_pop WHERE id = ?", (int(pop_id),))
        merged += 1
    return {"moved": moved, "merged": merged}


def _rewrite_building_ownership_for_transfer(
    conn: sqlite3.Connection,
    bld_id: int,
    *,
    scope_tag: str,
    from_tag: str,
    to_tag: str,
) -> int:
    updated = 0
    for ord_, owner_tag in conn.execute(
        """
        SELECT ord, owner_tag
        FROM st_bld_own
        WHERE bld_id = ?
        ORDER BY ord
        """,
        (bld_id,),
    ):
        effective = resolve_owner_tag_for_export(scope_tag, str(owner_tag))
        if effective != from_tag:
            continue
        new_owner = "" if to_tag == scope_tag else to_tag
        conn.execute(
            """
            UPDATE st_bld_own
            SET owner_tag = ?
            WHERE bld_id = ? AND ord = ?
            """,
            (new_owner, bld_id, int(ord_)),
        )
        updated += 1
    return updated


def _transfer_buildings_in_scope(
    conn: sqlite3.Connection,
    state: str,
    from_tag: str,
    to_tag: str,
) -> dict[str, int]:
    moved = 0
    ownership_updates = 0
    for bld_id, in conn.execute(
        """
        SELECT id FROM st_bld
        WHERE state = ? AND tag = ?
        ORDER BY id
        """,
        (state, from_tag),
    ):
        bld_id = int(bld_id)
        ownership_updates += _rewrite_building_ownership_for_transfer(
            conn,
            bld_id,
            scope_tag=from_tag,
            from_tag=from_tag,
            to_tag=to_tag,
        )
        conn.execute(
            "UPDATE st_bld SET tag = ? WHERE id = ?",
            (to_tag, bld_id),
        )
        moved += 1
    return {"moved": moved, "ownership_updates": ownership_updates}


def _rewrite_foreign_investments_for_annexation(
    conn: sqlite3.Connection,
    from_tag: str,
    to_tag: str,
) -> int:
    updated = 0
    for bld_id, scope_tag in conn.execute(
        "SELECT id, tag FROM st_bld ORDER BY id",
    ):
        bld_id = int(bld_id)
        scope_tag = str(scope_tag)
        for ord_, owner_tag in conn.execute(
            """
            SELECT ord, owner_tag
            FROM st_bld_own
            WHERE bld_id = ?
            ORDER BY ord
            """,
            (bld_id,),
        ):
            effective = resolve_owner_tag_for_export(scope_tag, str(owner_tag))
            if effective != from_tag:
                continue
            new_owner = "" if to_tag == scope_tag else to_tag
            conn.execute(
                """
                UPDATE st_bld_own
                SET owner_tag = ?
                WHERE bld_id = ? AND ord = ?
                """,
                (new_owner, bld_id, int(ord_)),
            )
            updated += 1
    return updated


def _province_owner(
    conn: sqlite3.Connection,
    province: str,
) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT state, tag FROM st_prov WHERE province = ?",
        (province,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def _target_owns_province(
    conn: sqlite3.Connection,
    *,
    state: str,
    tag: str,
    province: str,
) -> bool:
    owner = _province_owner(conn, province)
    return owner == (state, tag)


def _reassign_province_between_tags(
    conn: sqlite3.Connection,
    *,
    state: str,
    province: str,
    from_tag: str,
    to_tag: str,
) -> bool:
    """Move one province to another tag; return False if already owned by target."""
    owner = _province_owner(conn, province)
    if owner is None:
        raise ValueError(f"地块 {province} 未被任何国家拥有")
    owner_state, owner_tag = owner
    if owner_state != state or owner_tag != from_tag:
        raise ValueError(f"地块 {province} 不属于 {from_tag}/{state}")
    if owner_tag == to_tag:
        return False
    conn.execute(
        "UPDATE st_prov SET tag = ? WHERE province = ?",
        (to_tag, province),
    )
    return True


def _move_province(
    conn: sqlite3.Connection,
    *,
    state: str,
    province: str,
    from_tag: str,
    to_tag: str,
    new_scope_state_type: str,
) -> None:
    if from_tag == to_tag:
        raise ValueError("目标国家与当前归属相同")
    row = conn.execute(
        """
        SELECT 1 FROM st_prov
        WHERE state = ? AND tag = ? AND province = ?
        """,
        (state, from_tag, province),
    ).fetchone()
    if row is None:
        raise ValueError(f"地块 {province} 不属于 {from_tag}/{state}")
    if _target_owns_province(conn, state=state, tag=to_tag, province=province):
        raise ValueError(f"目标国家 {to_tag} 已拥有地块 {province}")
    _ensure_st_scope(conn, state, to_tag, state_type=new_scope_state_type)
    _reassign_province_between_tags(
        conn,
        state=state,
        province=province,
        from_tag=from_tag,
        to_tag=to_tag,
    )


def _transfer_state_contents(
    conn: sqlite3.Connection,
    state: str,
    from_tag: str,
    to_tag: str,
    *,
    state_type: str | None,
) -> dict:
    target_type = _resolve_target_state_type(
        conn, state, from_tag, to_tag, state_type
    )
    _ensure_st_scope(conn, state, to_tag, state_type=target_type)
    _apply_target_state_type(conn, state, to_tag, target_type)
    pop_stats = _merge_pops(conn, state, from_tag, to_tag)
    bld_stats = _transfer_buildings_in_scope(conn, state, from_tag, to_tag)
    _delete_st_scope_if_empty(conn, state, from_tag)
    return {
        "state_type": target_type,
        "pops": pop_stats,
        "buildings": bld_stats,
    }


def set_owner(
    conn: sqlite3.Connection,
    *,
    province_hex: str,
    new_tag: str,
    origin_tag: str | None = None,
) -> dict:
    """Move one province between tags (st_prov only; no pop/building cascade)."""
    province = normalize_province_hex(province_hex)
    state, current_tag = find_province_owner(conn, province)
    if origin_tag is not None and str(origin_tag) != current_tag:
        raise ValueError(
            f"origin_tag 不匹配：期望 {current_tag}，收到 {origin_tag}"
        )
    _validate_tag(conn, new_tag)
    target_was_inactive = not tag_has_provinces(conn, new_tag)
    undo = capture_set_owner_undo(
        conn,
        province=province,
        state=state,
        from_tag=current_tag,
        to_tag=new_tag,
    )
    origin_type = _scope_state_type(conn, state, current_tag) or "unincorporated"
    _move_province(
        conn,
        state=state,
        province=province,
        from_tag=current_tag,
        to_tag=new_tag,
        new_scope_state_type=origin_type,
    )
    result = {
        "op": "set_owner",
        "province": province_db_to_hex(province),
        "province_db": province,
        "state": state,
        "from_tag": current_tag,
        "to_tag": new_tag,
    }
    if not tag_has_provinces(conn, current_tag):
        note_country_destroyed(result, current_tag)
    if target_was_inactive:
        note_country_restored(result, new_tag)
    batch_id = write_batch(
        conn,
        summary=f"set_owner {province} {current_tag}->{new_tag}",
        payload=result,
        steps=[("set_owner", result, undo)],
    )
    result["batch_id"] = batch_id
    return result


def transfer_province(
    conn: sqlite3.Connection,
    *,
    province_hex: str,
    new_tag: str,
    origin_tag: str | None = None,
    state_type: str | None = None,
) -> dict:
    """Transfer one province; auto-upgrade to state / annex when needed."""
    province = normalize_province_hex(province_hex)
    state, current_tag = find_province_owner(conn, province)
    if origin_tag is not None and str(origin_tag) != current_tag:
        raise ValueError(
            f"origin_tag 不匹配：期望 {current_tag}，收到 {origin_tag}"
        )
    _validate_tag(conn, new_tag)
    if current_tag == new_tag:
        raise ValueError("目标国家与当前归属相同")

    target_was_inactive = not tag_has_provinces(conn, new_tag)
    was_last_in_state = count_provinces_in_scope(conn, state, current_tag) == 1
    undo = capture_transfer_undo(
        conn,
        state=state,
        origin_tag=current_tag,
    )
    target_type = _resolve_target_state_type(
        conn, state, current_tag, new_tag, state_type
    )

    _move_province(
        conn,
        state=state,
        province=province,
        from_tag=current_tag,
        to_tag=new_tag,
        new_scope_state_type=target_type,
    )

    op = "province_transfer"
    cascade: dict[str, object] = {}

    if was_last_in_state:
        cascade["state"] = _transfer_state_contents(
            conn,
            state,
            current_tag,
            new_tag,
            state_type=state_type,
        )
        op = "state_transfer"

    annexed = False
    if not tag_has_provinces(conn, current_tag):
        rows = capture_foreign_ownership_for_effective_owner(conn, current_tag)
        undo["foreign_ownership"] = foreign_ownership_undo(current_tag, rows)
        foreign_updates = _rewrite_foreign_investments_for_annexation(
            conn, current_tag, new_tag
        )
        cascade["annexation"] = {"foreign_ownership_updates": foreign_updates}
        annexed = True
        if op == "province_transfer":
            op = "annex_country"
        else:
            op = "state_transfer+annex"

    result = {
        "op": op,
        "province": province_db_to_hex(province),
        "province_db": province,
        "state": state,
        "from_tag": current_tag,
        "to_tag": new_tag,
        "was_last_in_state": was_last_in_state,
        "annexed_source_tag": annexed,
        "cascade": cascade,
    }
    if annexed:
        note_country_destroyed(result, current_tag)
    if target_was_inactive:
        note_country_restored(result, new_tag)
    batch_id = write_batch(
        conn,
        summary=f"transfer_province {province} {current_tag}->{new_tag} ({op})",
        payload=result,
        steps=[("transfer_province", result, undo)],
    )
    result["batch_id"] = batch_id
    return result


def transfer_state(
    conn: sqlite3.Connection,
    *,
    state: str,
    origin_tag: str,
    new_tag: str,
    state_type: str | None = None,
    record_batch: bool = True,
) -> dict:
    """Transfer an entire tag+state scope (all provinces, pops, buildings)."""
    state = str(state)
    origin_tag = str(origin_tag)
    new_tag = str(new_tag)
    _validate_tag(conn, new_tag)
    if origin_tag == new_tag:
        raise ValueError("目标国家与当前归属相同")
    provinces = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT province FROM st_prov
            WHERE state = ? AND tag = ?
            ORDER BY province
            """,
            (state, origin_tag),
        )
    ]
    if not provinces:
        raise ValueError(f"{origin_tag} 在 {state} 没有地块")

    target_was_inactive = not tag_has_provinces(conn, new_tag)
    undo = capture_transfer_undo(
        conn,
        state=state,
        origin_tag=origin_tag,
    )

    target_type = _resolve_target_state_type(
        conn, state, origin_tag, new_tag, state_type
    )
    _ensure_st_scope(conn, state, new_tag, state_type=target_type)
    _apply_target_state_type(conn, state, new_tag, target_type)

    provinces_moved = 0
    provinces_deduped = 0
    for province in provinces:
        if _reassign_province_between_tags(
            conn,
            state=state,
            province=province,
            from_tag=origin_tag,
            to_tag=new_tag,
        ):
            provinces_moved += 1
        else:
            provinces_deduped += 1

    cascade = {
        "state": _transfer_state_contents(
            conn,
            state,
            origin_tag,
            new_tag,
            state_type=state_type,
        ),
    }

    annexed = False
    if not tag_has_provinces(conn, origin_tag):
        rows = capture_foreign_ownership_for_effective_owner(conn, origin_tag)
        undo["foreign_ownership"] = foreign_ownership_undo(origin_tag, rows)
        foreign_updates = _rewrite_foreign_investments_for_annexation(
            conn, origin_tag, new_tag
        )
        cascade["annexation"] = {"foreign_ownership_updates": foreign_updates}
        annexed = True

    op = "state_transfer+annex" if annexed else "state_transfer"
    result = {
        "op": op,
        "state": state,
        "from_tag": origin_tag,
        "to_tag": new_tag,
        "provinces_moved": provinces_moved,
        "provinces_deduped": provinces_deduped,
        "provinces_in_scope": len(provinces),
        "annexed_source_tag": annexed,
        "cascade": cascade,
    }
    if annexed:
        note_country_destroyed(result, origin_tag)
    if target_was_inactive:
        note_country_restored(result, new_tag)
    if record_batch:
        batch_id = write_batch(
            conn,
            summary=f"transfer_state {origin_tag}/{state}->{new_tag} ({op})",
            payload=result,
            steps=[("transfer_state", result, undo)],
        )
        result["batch_id"] = batch_id
    return result


def transfer_scope_state(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    new_tag: str,
    state_type: str | None = None,
) -> dict:
    """Transfer the entire current scope state ``(tag, state)``."""
    return transfer_state(
        conn,
        state=state,
        origin_tag=tag,
        new_tag=new_tag,
        state_type=state_type,
    )


def _require_scope(conn: sqlite3.Connection, tag: str, state: str) -> str:
    state_type = _scope_state_type(conn, state, tag)
    if state_type is None:
        raise ValueError(f"scope state 不存在：{tag}/{state}")
    return state_type


def tag_has_provinces_outside_state(
    conn: sqlite3.Connection, tag: str, state: str
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM st_prov WHERE tag = ? AND state != ? LIMIT 1",
        (tag, state),
    ).fetchone()
    return row is not None


def _other_tags_in_state(
    conn: sqlite3.Connection, state: str, tag: str
) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            """
            SELECT DISTINCT tag FROM st_prov
            WHERE state = ? AND tag != ?
            ORDER BY tag
            """,
            (state, tag),
        )
    ]


def _scope_stats(conn: sqlite3.Connection, state: str, tag: str) -> dict[str, int]:
    provinces = count_provinces_in_scope(conn, state, tag)
    pop_row = conn.execute(
        "SELECT COALESCE(SUM(size), 0) FROM st_pop WHERE state = ? AND tag = ?",
        (state, tag),
    ).fetchone()
    bld_row = conn.execute(
        "SELECT COUNT(*) FROM st_bld WHERE state = ? AND tag = ?",
        (state, tag),
    ).fetchone()
    return {
        "provinces": provinces,
        "population": int(pop_row[0]) if pop_row else 0,
        "buildings": int(bld_row[0]) if bld_row else 0,
    }


def load_state_expansion_preview(
    conn: sqlite3.Connection, tag: str, state: str
) -> dict:
    """Preview absorbing other tags' holdings in the same geographic state."""
    tag = str(tag)
    state = str(state)
    state_type = _require_scope(conn, tag, state)
    geo_row = conn.execute(
        "SELECT COUNT(*) FROM ref_sr_prov WHERE state = ?", (state,)
    ).fetchone()
    geo_province_count = int(geo_row[0]) if geo_row else 0
    own_stats = _scope_stats(conn, state, tag)
    other_tags: list[dict] = []
    for other_tag in _other_tags_in_state(conn, state, tag):
        stats = _scope_stats(conn, state, other_tag)
        only_here = not tag_has_provinces_outside_state(conn, other_tag, state)
        other_tags.append(
            {
                "tag": other_tag,
                "provinces": stats["provinces"],
                "population": stats["population"],
                "buildings": stats["buildings"],
                "would_annex": only_here,
            }
        )
    return {
        "tag": tag,
        "state": state,
        "state_type": state_type,
        "is_split": bool(other_tags),
        "geo_province_count": geo_province_count,
        "owned_province_count": own_stats["provinces"],
        "other_tags": other_tags,
        "other_province_count": sum(item["provinces"] for item in other_tags),
    }


def _expand_scope_to_full_state_body(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    record_batch: bool = True,
) -> dict:
    """Core logic for absorbing other tags' scopes in ``state`` into ``tag``."""
    tag = str(tag)
    state = str(state)
    current_type = _require_scope(conn, tag, state)
    other_tags = _other_tags_in_state(conn, state, tag)
    if not other_tags:
        raise ValueError(f"{tag} 已拥有 {state} 的全部分属地块")

    geo_undo = capture_geo_state_snapshot(conn, state)
    foreign_undos: dict[str, dict] = {}

    transfers: list[dict] = []
    annexed_tags: list[str] = []
    total_provinces = 0

    for other_tag in other_tags:
        if not tag_has_provinces_outside_state(conn, other_tag, state):
            foreign_undos[other_tag] = foreign_ownership_undo(
                other_tag,
                capture_foreign_ownership_for_effective_owner(conn, other_tag),
            )
        result = transfer_state(
            conn,
            state=state,
            origin_tag=other_tag,
            new_tag=tag,
            state_type=None,
            record_batch=False,
        )
        transfers.append(result)
        total_provinces += int(result["provinces_moved"])
        if result["annexed_source_tag"]:
            annexed_tags.append(other_tag)

    _apply_target_state_type(conn, state, tag, current_type)

    op = "expand_to_full_state+annex" if annexed_tags else "expand_to_full_state"
    result = {
        "op": op,
        "tag": tag,
        "state": state,
        "to_tag": tag,
        "from_tags": other_tags,
        "annexed_tags": annexed_tags,
        "provinces_moved": total_provinces,
        "state_type": current_type,
        "transfers": transfers,
    }
    note_annexed_tags(result, annexed_tags)
    undo = {
        "kind": "expand_to_full_state",
        "geo_state": geo_undo,
        "foreign_ownership": foreign_undos,
    }
    if record_batch:
        batch_id = write_batch(
            conn,
            summary=(
                f"expand_to_full_state {tag}/{state} "
                f"<- {','.join(other_tags)} ({op})"
            ),
            payload=result,
            steps=[("expand_to_full_state", result, undo)],
        )
        result["batch_id"] = batch_id
    return result


def expand_scope_to_full_state(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    record_batch: bool = True,
) -> dict:
    """Absorb every other tag's scope in ``state`` into ``(tag, state)``.

    Each absorbed ``(other_tag, state)`` runs full state transfer (pops,
    buildings, ownership). If ``other_tag`` has no provinces left anywhere,
    foreign investments are rewritten (annexation). The expanding tag's
    incorporation status in this state is preserved.
    """
    with atomic_edit(conn):
        return _expand_scope_to_full_state_body(
            conn,
            tag=tag,
            state=state,
            record_batch=record_batch,
        )


def annex_country(
    conn: sqlite3.Connection,
    *,
    origin_tag: str,
    new_tag: str,
    state_type: str = "unincorporated",
) -> dict:
    """Transfer every state owned by ``origin_tag`` to ``new_tag`` (fixed state_type per scope)."""
    with atomic_edit(conn):
        origin_tag = str(origin_tag)
        new_tag = str(new_tag)
        _validate_tag(conn, new_tag)
        if origin_tag == new_tag:
            raise ValueError("目标国家与当前归属相同")
        states = _states_for_tag(conn, origin_tag)
        if not states:
            raise ValueError(f"{origin_tag} 没有任何地块")

        foreign_undo = foreign_ownership_undo(
            origin_tag,
            capture_foreign_ownership_for_effective_owner(conn, origin_tag),
        )
        steps: list[tuple[str, object, object | None]] = []
        transfers: list[dict] = []
        foreign_updates = 0
        for state in states:
            undo = capture_transfer_undo(
                conn,
                state=state,
                origin_tag=origin_tag,
            )
            result = transfer_state(
                conn,
                state=state,
                origin_tag=origin_tag,
                new_tag=new_tag,
                state_type=state_type,
                record_batch=False,
            )
            transfers.append(result)
            steps.append(("transfer_state", result, undo))
            if result.get("annexed_source_tag"):
                foreign_updates = int(
                    result["cascade"]["annexation"]["foreign_ownership_updates"]
                )

        if foreign_updates:
            steps.append(
                (
                    "rewrite_foreign_ownership",
                    {
                        "from_tag": origin_tag,
                        "to_tag": new_tag,
                        "count": foreign_updates,
                    },
                    foreign_undo,
                )
            )

        result = {
            "op": "annex_country",
            "from_tag": origin_tag,
            "to_tag": new_tag,
            "tag": new_tag,
            "victim_tag": origin_tag,
            "states_transferred": len(states),
            "transfers": transfers,
            "foreign_ownership_updates": foreign_updates,
        }
        note_country_destroyed(result, origin_tag)
        batch_id = write_batch(
            conn,
            summary=f"annex_country {origin_tag}->{new_tag} ({len(states)} states)",
            payload=result,
            steps=steps,
        )
        result["batch_id"] = batch_id
        return result


def list_split_states_for_tag(conn: sqlite3.Connection, tag: str) -> list[str]:
    """Geographic states where ``tag`` shares land with other tags."""
    return [
        str(row[0])
        for row in conn.execute(
            """
            SELECT DISTINCT p.state
            FROM st_prov p
            JOIN st_prov o ON o.state = p.state AND o.tag != p.tag
            WHERE p.tag = ?
            ORDER BY p.state
            """,
            (tag,),
        )
    ]


def _states_for_tag(conn: sqlite3.Connection, tag: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            """
            SELECT DISTINCT state FROM st_prov
            WHERE tag = ?
            ORDER BY state
            """,
            (tag,),
        )
    ]


def _annex_state_type_for_merge(
    conn: sqlite3.Connection,
    state: str,
    acquirer_tag: str,
    victim_tag: str,
    *,
    force_unincorporated: bool,
) -> str:
    """Pick incorporation for annexed land without altering acquirer's existing scopes."""
    existing = _scope_state_type(conn, state, acquirer_tag)
    if existing is not None:
        return existing
    if force_unincorporated:
        return "unincorporated"
    victim_type = _scope_state_type(conn, state, victim_tag)
    return victim_type or "unincorporated"


def annex_country_into(
    conn: sqlite3.Connection,
    *,
    acquirer_tag: str,
    victim_tag: str,
    force_unincorporated: bool = False,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Annex ``victim_tag`` into ``acquirer_tag`` scope-by-scope (no expand).

    Existing partial ownership in acquirer states is unchanged; only victim
    holdings are transferred. When acquirer already owns part of a state,
    its incorporation there is kept.
    """
    with atomic_edit(conn):
        acquirer_tag = str(acquirer_tag)
        victim_tag = str(victim_tag)
        _validate_tag(conn, acquirer_tag)
        _validate_tag(conn, victim_tag)
        if acquirer_tag == victim_tag:
            raise ValueError("不能与自身合并")
        if not tag_has_provinces(conn, victim_tag):
            raise ValueError(f"{victim_tag} 没有任何地块")

        states = _states_for_tag(conn, victim_tag)
        foreign_undo = foreign_ownership_undo(
            victim_tag,
            capture_foreign_ownership_for_effective_owner(conn, victim_tag),
        )
        steps: list[tuple[str, object, object | None]] = []
        transfers: list[dict] = []
        foreign_updates = 0
        tick = make_loop_progress(on_progress, len(states), prefix="吞并地区 ")
        for state in states:
            st_type = _annex_state_type_for_merge(
                conn,
                state,
                acquirer_tag,
                victim_tag,
                force_unincorporated=force_unincorporated,
            )
            undo = capture_transfer_undo(
                conn,
                state=state,
                origin_tag=victim_tag,
            )
            result = transfer_state(
                conn,
                state=state,
                origin_tag=victim_tag,
                new_tag=acquirer_tag,
                state_type=st_type,
                record_batch=False,
            )
            transfers.append(result)
            steps.append(("transfer_state", result, undo))
            tick(f"正在吞并 {state}")
            if result.get("annexed_source_tag"):
                foreign_updates = int(
                    result["cascade"]["annexation"]["foreign_ownership_updates"]
                )

        op = (
            "annex_country_unincorporated"
            if force_unincorporated
            else "annex_country_preserve"
        )
        result = {
            "op": op,
            "tag": acquirer_tag,
            "to_tag": acquirer_tag,
            "victim_tag": victim_tag,
            "from_tag": victim_tag,
            "states_transferred": len(states),
            "transfers": transfers,
            "foreign_ownership_updates": foreign_updates,
        }
        note_country_destroyed(result, victim_tag)
        if foreign_updates:
            steps.append(
                (
                    "rewrite_foreign_ownership",
                    {
                        "from_tag": victim_tag,
                        "to_tag": acquirer_tag,
                        "count": foreign_updates,
                    },
                    foreign_undo,
                )
            )
        batch_id = write_batch(
            conn,
            summary=f"{op} {victim_tag}->{acquirer_tag} ({len(states)} states)",
            payload=result,
            steps=steps,
        )
        result["batch_id"] = batch_id
        return result


def expand_all_split_states(
    conn: sqlite3.Connection,
    *,
    tag: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Expand every split geographic state owned by ``tag`` to full state control."""
    with atomic_edit(conn):
        tag = str(tag)
        if not tag_has_provinces(conn, tag):
            raise ValueError(f"{tag} 没有任何地块")
        if on_progress is not None:
            on_progress(12, "正在查找分属地区…")
        split_states = list_split_states_for_tag(conn, tag)
        if not split_states:
            raise ValueError(f"{tag} 没有分属地区")

        expansions: list[dict] = []
        annexed_tags: set[str] = set()
        total_provinces = 0
        steps: list[tuple[str, object, object | None]] = []
        tick = make_loop_progress(on_progress, len(split_states), prefix="扩展分属 ")
        for state in split_states:
            geo_undo = capture_geo_state_snapshot(conn, state)
            foreign_undos: dict[str, dict] = {}
            for other_tag in _other_tags_in_state(conn, state, tag):
                if not tag_has_provinces_outside_state(conn, other_tag, state):
                    foreign_undos[other_tag] = foreign_ownership_undo(
                        other_tag,
                        capture_foreign_ownership_for_effective_owner(
                            conn, other_tag
                        ),
                    )
            result = _expand_scope_to_full_state_body(
                conn, tag=tag, state=state, record_batch=False
            )
            expansions.append(result)
            total_provinces += int(result["provinces_moved"])
            annexed_tags.update(result.get("annexed_tags", []))
            tick(f"正在扩展 {state}")
            steps.append(
                (
                    "expand_to_full_state",
                    result,
                    {
                        "kind": "expand_to_full_state",
                        "geo_state": geo_undo,
                        "foreign_ownership": foreign_undos,
                    },
                )
            )

        op = "expand_all_split_states+annex" if annexed_tags else "expand_all_split_states"
        payload = {
            "op": op,
            "tag": tag,
            "to_tag": tag,
            "states_expanded": split_states,
            "provinces_moved": total_provinces,
            "annexed_tags": sorted(annexed_tags),
            "expansions": expansions,
        }
        note_annexed_tags(payload, annexed_tags)
        batch_id = write_batch(
            conn,
            summary=f"expand_all_split_states {tag} ({len(split_states)} states)",
            payload=payload,
            steps=steps,
        )
        payload["batch_id"] = batch_id
        return payload


def change_tag(
    conn: sqlite3.Connection,
    *,
    old_tag: str,
    new_tag: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Rename country tag on all owned scopes; ``new_tag`` must be inactive."""
    with atomic_edit(conn):
        old_tag = str(old_tag)
        new_tag = str(new_tag)
        _validate_tag(conn, new_tag)
        if old_tag == new_tag:
            raise ValueError("新旧 tag 相同")
        if tag_has_provinces(conn, new_tag):
            raise ValueError(f"{new_tag} 已有地区，必须是 inactive tag")
        if not tag_has_provinces(conn, old_tag):
            raise ValueError(f"{old_tag} 没有任何地块")

        undo = capture_change_tag_undo(conn, old_tag=old_tag, new_tag=new_tag)

        scopes = [
            (str(state), str(state_type or "incorporated"))
            for state, state_type in conn.execute(
                "SELECT state, state_type FROM st WHERE tag = ? ORDER BY state",
                (old_tag,),
            )
        ]
        if not scopes:
            raise ValueError(f"{old_tag} 没有 scope state 记录")

        tick = make_loop_progress(on_progress, len(scopes), prefix="迁移 scope ")
        for state, state_type in scopes:
            _ensure_st_scope(conn, state, new_tag, state_type=state_type)
            _apply_target_state_type(conn, state, new_tag, state_type)
            tick(f"正在迁移 {state}")

        if on_progress is not None:
            on_progress(88, "正在更新全局引用…")
        conn.execute("UPDATE st_prov SET tag = ? WHERE tag = ?", (new_tag, old_tag))
        conn.execute("UPDATE st_pop SET tag = ? WHERE tag = ?", (new_tag, old_tag))
        conn.execute("UPDATE st_bld SET tag = ? WHERE tag = ?", (new_tag, old_tag))
        conn.execute("DELETE FROM st WHERE tag = ?", (old_tag,))

        foreign_updates = _rewrite_foreign_investments_for_annexation(
            conn, old_tag, new_tag
        )

        states = [state for state, _ in scopes]
        result = {
            "op": "change_tag",
            "from_tag": old_tag,
            "to_tag": new_tag,
            "tag": new_tag,
            "states_moved": states,
            "scope_count": len(scopes),
            "foreign_ownership_updates": foreign_updates,
        }
        note_country_destroyed(result, old_tag)
        note_country_restored(result, new_tag)
        batch_id = write_batch(
            conn,
            summary=f"change_tag {old_tag}->{new_tag} ({len(scopes)} scopes)",
            payload=result,
            steps=[("change_tag", result, undo)],
        )
        result["batch_id"] = batch_id
        return result


def load_country_macro_preview(conn: sqlite3.Connection, tag: str) -> dict:
    tag = str(tag)
    if not tag_has_provinces(conn, tag):
        raise ValueError(f"{tag} 没有任何地块")

    split_states = list_split_states_for_tag(conn, tag)
    split_details = [
        {
            "state": state,
            **{
                k: v
                for k, v in load_state_expansion_preview(conn, tag, state).items()
                if k not in ("tag", "state")
            },
        }
        for state in split_states
    ]
    active_tags = sorted(
        {
            str(row[0])
            for row in conn.execute("SELECT DISTINCT tag FROM st_prov ORDER BY tag")
        }
    )
    all_tags = [
        str(row[0]) for row in conn.execute("SELECT tag FROM ref_tag ORDER BY tag")
    ]
    unincorporated_states = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT state FROM st
            WHERE tag = ? AND state_type != 'incorporated'
            ORDER BY state
            """,
            (tag,),
        )
    ]
    return {
        "tag": tag,
        "state_count": len(_states_for_tag(conn, tag)),
        "province_count": sum(
            count_provinces_in_scope(conn, state, tag)
            for state in _states_for_tag(conn, tag)
        ),
        "split_state_count": len(split_states),
        "split_states": split_details,
        "annex_victim_tags": [t for t in active_tags if t != tag],
        "change_tag_targets": [t for t in all_tags if t not in active_tags],
        "unincorporated_state_count": len(unincorporated_states),
        "unincorporated_states": unincorporated_states,
        "release_country_candidates": _release_candidates_for_macro(conn, tag),
        "acquire_homelands": _acquire_homelands_for_macro(conn, tag),
        "homeland_batch": _homeland_batch_for_macro(conn, tag),
        "pop_convert": _pop_convert_for_macro(conn, tag),
    }


def _release_candidates_for_macro(conn: sqlite3.Connection, tag: str) -> list[dict]:
    from interactive_map.edit.country_homeland_macro import (
        list_release_country_candidates,
    )

    try:
        return list_release_country_candidates(conn, tag)
    except Exception:
        return []


def _acquire_homelands_for_macro(conn: sqlite3.Connection, tag: str) -> dict:
    from interactive_map.edit.country_homeland_macro import load_acquire_homelands_preview

    try:
        return load_acquire_homelands_preview(conn, tag)
    except ValueError:
        return {
            "tag": tag,
            "primary_cultures": primary_cultures(conn, tag),
            "states": [],
            "state_count": 0,
            "foreign_provinces": 0,
        }


def _homeland_batch_for_macro(conn: sqlite3.Connection, tag: str) -> dict:
    from interactive_map.edit.country_homeland_macro import (
        load_homeland_batch_macro_preview,
    )

    try:
        return load_homeland_batch_macro_preview(conn, tag)
    except ValueError:
        return {
            "tag": tag,
            "owned_state_count": 0,
            "owned_states": [],
            "removable_cultures": [],
            "fillable_state_count": 0,
            "fillable_states": [],
            "cultures": [],
        }


def _pop_convert_for_macro(conn: sqlite3.Connection, tag: str) -> dict:
    from interactive_map.edit.country_pop_macro import load_pop_convert_macro_preview

    try:
        return load_pop_convert_macro_preview(conn, tag)
    except ValueError:
        return {
            "tag": tag,
            "convertible_cultures": [],
            "all_cultures": [],
            "convertible_religions": [],
            "all_religions": [],
        }


COUNTRY_MACRO_SECTIONS: frozenset[str] = frozenset(
    {
        "expand",
        "incorporate",
        "annex",
        "change-tag",
        "acquire",
        "homeland-remove",
        "homeland-clear",
        "homeland-add",
        "pop-culture",
        "pop-religion",
        "release",
    }
)


def _country_macro_expand_section(conn: sqlite3.Connection, tag: str) -> dict:
    split_states = list_split_states_for_tag(conn, tag)
    split_details = [
        {
            "state": state,
            **{
                k: v
                for k, v in load_state_expansion_preview(conn, tag, state).items()
                if k not in ("tag", "state")
            },
        }
        for state in split_states
    ]
    return {
        "tag": tag,
        "section": "expand",
        "split_state_count": len(split_states),
        "split_states": split_details,
    }


def _country_macro_incorporate_section(conn: sqlite3.Connection, tag: str) -> dict:
    unincorporated_states = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT state FROM st
            WHERE tag = ? AND state_type != 'incorporated'
            ORDER BY state
            """,
            (tag,),
        )
    ]
    return {
        "tag": tag,
        "section": "incorporate",
        "unincorporated_state_count": len(unincorporated_states),
        "unincorporated_states": unincorporated_states,
    }


def _country_macro_annex_section(conn: sqlite3.Connection, tag: str) -> dict:
    active_tags = sorted(
        {
            str(row[0])
            for row in conn.execute("SELECT DISTINCT tag FROM st_prov ORDER BY tag")
        }
    )
    return {
        "tag": tag,
        "section": "annex",
        "annex_victim_tags": [t for t in active_tags if t != tag],
        "transfer_options": load_transfer_options(conn),
    }


def _country_macro_change_tag_section(conn: sqlite3.Connection, tag: str) -> dict:
    active_tags = {
        str(row[0])
        for row in conn.execute("SELECT DISTINCT tag FROM st_prov")
    }
    all_tags = [
        str(row[0]) for row in conn.execute("SELECT tag FROM ref_tag ORDER BY tag")
    ]
    states = _states_for_tag(conn, tag)
    return {
        "tag": tag,
        "section": "change-tag",
        "change_tag_targets": [t for t in all_tags if t not in active_tags],
        "state_count": len(states),
        "province_count": sum(
            count_provinces_in_scope(conn, state, tag) for state in states
        ),
        "transfer_options": load_transfer_options(conn),
    }


def load_country_macro_section(
    conn: sqlite3.Connection, tag: str, section: str
) -> dict:
    tag = str(tag)
    section = str(section)
    if section not in COUNTRY_MACRO_SECTIONS:
        raise ValueError(f"未知国家宏操作节：{section}")
    if not tag_has_provinces(conn, tag):
        raise ValueError(f"{tag} 没有任何地块")

    if section == "expand":
        return _country_macro_expand_section(conn, tag)
    if section == "incorporate":
        return _country_macro_incorporate_section(conn, tag)
    if section == "annex":
        return _country_macro_annex_section(conn, tag)
    if section == "change-tag":
        return _country_macro_change_tag_section(conn, tag)
    if section == "acquire":
        return {
            "tag": tag,
            "section": section,
            "acquire_homelands": _acquire_homelands_for_macro(conn, tag),
        }
    if section == "homeland-remove":
        batch = _homeland_batch_for_macro(conn, tag)
        return {
            "tag": tag,
            "section": section,
            "owned_state_count": batch.get("owned_state_count", 0),
            "removable_cultures": batch.get("removable_cultures", []),
            "cultures": batch.get("cultures", []),
        }
    if section == "homeland-clear":
        from interactive_map.edit.country_homeland_macro import (
            load_remove_all_homelands_preview,
        )

        preview = load_remove_all_homelands_preview(conn, tag)
        return {
            "tag": tag,
            "section": section,
            "split_state_count": preview["split_state_count"],
            "include_split": preview["include_split"],
            "exclude_split": preview["exclude_split"],
        }
    if section == "homeland-add":
        batch = _homeland_batch_for_macro(conn, tag)
        return {
            "tag": tag,
            "section": section,
            "owned_state_count": batch.get("owned_state_count", 0),
            "fillable_state_count": batch.get("fillable_state_count", 0),
            "fillable_states": batch.get("fillable_states", []),
            "cultures": batch.get("cultures", []),
        }
    if section == "pop-culture":
        preview = _pop_convert_for_macro(conn, tag)
        return {
            "tag": tag,
            "section": section,
            "convertible_cultures": preview.get("convertible_cultures", []),
            "all_cultures": preview.get("all_cultures", []),
        }
    if section == "pop-religion":
        preview = _pop_convert_for_macro(conn, tag)
        return {
            "tag": tag,
            "section": section,
            "convertible_religions": preview.get("convertible_religions", []),
            "all_religions": preview.get("all_religions", []),
        }
    if section == "release":
        return {
            "tag": tag,
            "section": section,
            "release_country_candidates": _release_candidates_for_macro(conn, tag),
            "transfer_options": load_transfer_options(conn),
        }
    raise ValueError(f"未知国家宏操作节：{section}")


def load_transfer_options(conn: sqlite3.Connection) -> dict:
    tags = [
        str(row[0])
        for row in conn.execute("SELECT tag FROM ref_tag ORDER BY tag")
    ]
    active_tags = sorted(
        {
            str(row[0])
            for row in conn.execute("SELECT DISTINCT tag FROM st_prov ORDER BY tag")
        }
    )
    return {
        "tags": tags,
        "active_tags": active_tags,
        "state_types": [
            {"value": "incorporated", "label": "已整合"},
            {"value": "unincorporated", "label": "未整合"},
        ],
    }
