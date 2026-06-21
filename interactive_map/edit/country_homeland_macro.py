"""Country macro ops based on primary cultures and geographic homelands."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from interactive_map.macro_edit_job import make_loop_progress
from interactive_map.edit.country_fate import (
    note_annexed_tags,
    note_country_destroyed,
    note_country_restored,
)
from interactive_map.edit.log import write_batch
from interactive_map.edit.atomic import atomic_edit
from interactive_map.edit.snapshot import (
    capture_foreign_ownership_for_effective_owner,
    capture_toggle_undo,
    capture_transfer_undo,
    foreign_ownership_undo,
)
from interactive_map.edit.state_geo import _ensure_geo_state, _validate_culture
from interactive_map.edit.transfer import (
    _apply_target_state_type,
    _scope_state_type,
    count_provinces_in_scope,
    list_split_states_for_tag,
    primary_cultures,
    tag_has_provinces,
    tag_has_provinces_outside_state,
    transfer_state,
    _validate_tag,
)


def _active_tags(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT DISTINCT tag FROM st_prov ORDER BY tag")
    }


def _geo_state_homelands(conn: sqlite3.Connection, state: str) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT culture FROM geo_homeland WHERE state = ? ORDER BY culture",
            (state,),
        )
    }


def _geographic_states_owned(conn: sqlite3.Connection, tag: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT state FROM st_prov WHERE tag = ? ORDER BY state",
            (tag,),
        )
    ]


def _homeland_cultures_on_owned_territory(
    conn: sqlite3.Connection,
    tag: str,
) -> set[str]:
    cultures: set[str] = set()
    for state in _geographic_states_owned(conn, tag):
        cultures.update(_geo_state_homelands(conn, state))
    return cultures


def _geo_states_with_primary_homelands(
    conn: sqlite3.Connection,
    cultures: set[str],
    *,
    on_progress: Callable[[int, str], None] | None = None,
) -> list[str]:
    if not cultures:
        return []
    rows = conn.execute("SELECT DISTINCT state FROM geo_homeland ORDER BY state").fetchall()
    matched: list[str] = []
    total = len(rows)
    for index, (state,) in enumerate(rows, start=1):
        geo_state = str(state)
        if _geo_state_homelands(conn, geo_state) & cultures:
            matched.append(geo_state)
        if on_progress is not None and (index == 1 or index == total or index % 50 == 0):
            pct = 10 + int(index * 8 / max(total, 1))
            on_progress(pct, f"正在扫描文化本土（{index}/{total}）")
    return matched


def _states_to_release_for_target(
    conn: sqlite3.Connection,
    releaser_tag: str,
    target_tag: str,
) -> list[dict]:
    target_primary = set(primary_cultures(conn, target_tag))
    if not target_primary:
        return []
    states: list[dict] = []
    for state in _geographic_states_owned(conn, releaser_tag):
        homelands = _geo_state_homelands(conn, state)
        if not (homelands & target_primary):
            continue
        scope_type = _scope_state_type(conn, state, releaser_tag) or "incorporated"
        states.append(
            {
                "state": state,
                "homelands": sorted(homelands),
                "matching_cultures": sorted(homelands & target_primary),
                "provinces": count_provinces_in_scope(conn, state, releaser_tag),
                "state_type": scope_type,
            }
        )
    return states


def list_release_country_candidates(
    conn: sqlite3.Connection,
    releaser_tag: str,
) -> list[dict]:
    releaser_tag = str(releaser_tag)
    if not tag_has_provinces(conn, releaser_tag):
        return []

    homeland_cultures = _homeland_cultures_on_owned_territory(conn, releaser_tag)
    active = _active_tags(conn)
    candidates: list[dict] = []

    for (target_tag,) in conn.execute("SELECT tag FROM ref_tag ORDER BY tag"):
        target_tag = str(target_tag)
        if target_tag == releaser_tag or target_tag in active:
            continue
        target_primary = set(primary_cultures(conn, target_tag))
        if not target_primary:
            continue
        if not (target_primary & homeland_cultures):
            continue
        release_states = _states_to_release_for_target(conn, releaser_tag, target_tag)
        if not release_states:
            continue
        candidates.append(
            {
                "tag": target_tag,
                "primary_cultures": sorted(target_primary),
                "states": release_states,
                "state_count": len(release_states),
                "province_count": sum(int(item["provinces"]) for item in release_states),
            }
        )
    return candidates


def load_release_country_preview(
    conn: sqlite3.Connection,
    releaser_tag: str,
    *,
    target_tag: str | None = None,
) -> dict:
    releaser_tag = str(releaser_tag)
    candidates = list_release_country_candidates(conn, releaser_tag)
    selected = None
    if target_tag:
        target_tag = str(target_tag)
        selected = next((item for item in candidates if item["tag"] == target_tag), None)
        if selected is None:
            raise ValueError(f"无法向 {target_tag} 释放国家")
    return {
        "tag": releaser_tag,
        "homeland_cultures_on_territory": sorted(
            _homeland_cultures_on_owned_territory(conn, releaser_tag)
        ),
        "candidates": candidates,
        "selected": selected,
    }


def release_country(
    conn: sqlite3.Connection,
    *,
    tag: str,
    target_tag: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Transfer releaser scopes that are homelands of ``target_tag`` primary cultures."""
    with atomic_edit(conn):
        tag = str(tag)
        target_tag = str(target_tag)
        _validate_tag(conn, target_tag)
        if tag == target_tag:
            raise ValueError("不能释放给自己")
        if tag_has_provinces(conn, target_tag):
            raise ValueError(f"{target_tag} 已有地区，必须是 inactive tag")
        if not tag_has_provinces(conn, tag):
            raise ValueError(f"{tag} 没有任何地块")

        preview = load_release_country_preview(conn, tag, target_tag=target_tag)
        selected = preview["selected"]
        assert selected is not None

        transfers: list[dict] = []
        annexed_releaser = False
        foreign_undo = foreign_ownership_undo(
            tag,
            capture_foreign_ownership_for_effective_owner(conn, tag),
        )
        steps: list[tuple[str, object, object | None]] = []
        foreign_updates = 0
        planned = [
            str(state_info["state"])
            for state_info in selected["states"]
            if count_provinces_in_scope(conn, str(state_info["state"]), tag) > 0
        ]
        tick = make_loop_progress(on_progress, len(planned), prefix="释放地区 ")
        for state_info in selected["states"]:
            state = str(state_info["state"])
            if count_provinces_in_scope(conn, state, tag) == 0:
                continue
            undo = capture_transfer_undo(
                conn,
                state=state,
                origin_tag=tag,
            )
            result = transfer_state(
                conn,
                state=state,
                origin_tag=tag,
                new_tag=target_tag,
                state_type="incorporated",
                record_batch=False,
            )
            transfers.append(result)
            steps.append(("transfer_state", result, undo))
            tick(f"正在释放 {state}")
            if result.get("annexed_source_tag"):
                annexed_releaser = True
                foreign_updates = int(
                    result["cascade"]["annexation"]["foreign_ownership_updates"]
                )

        if not transfers:
            raise ValueError("没有可转移的地区")

        op = "release_country+annex" if annexed_releaser else "release_country"
        payload = {
            "op": op,
            "tag": tag,
            "from_tag": tag,
            "to_tag": target_tag,
            "target_tag": target_tag,
            "states_released": [str(item["state"]) for item in selected["states"]],
            "states_transferred": len(transfers),
            "provinces_moved": sum(int(item["provinces_moved"]) for item in transfers),
            "annexed_releaser": annexed_releaser,
            "transfers": transfers,
            "foreign_ownership_updates": foreign_updates,
        }
        if foreign_updates:
            steps.append(
                (
                    "rewrite_foreign_ownership",
                    {
                        "from_tag": tag,
                        "to_tag": target_tag,
                        "count": foreign_updates,
                    },
                    foreign_undo,
                )
            )
        note_country_restored(payload, target_tag)
        if annexed_releaser:
            note_country_destroyed(payload, tag)
        batch_id = write_batch(
            conn,
            summary=f"{op} {tag}->{target_tag} ({len(transfers)} states)",
            payload=payload,
            steps=steps,
        )
        payload["batch_id"] = batch_id
        return payload


def load_acquire_homelands_preview(
    conn: sqlite3.Connection,
    tag: str,
    *,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    tag = str(tag)
    if not tag_has_provinces(conn, tag):
        raise ValueError(f"{tag} 没有任何地块")

    primary = set(primary_cultures(conn, tag))
    if not primary:
        raise ValueError(f"{tag} 没有定义主流文化")

    if on_progress is not None:
        on_progress(10, "正在分析主流文化…")

    states: list[dict] = []
    total_foreign_provinces = 0
    homelands = _geo_states_with_primary_homelands(conn, primary, on_progress=on_progress)
    if on_progress is not None:
        on_progress(18, f"正在匹配分属地区（{len(homelands)} 个本土 state）…")
    for geo_state in homelands:
        homelands = sorted(_geo_state_homelands(conn, geo_state) & primary)
        tags_in_state = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT DISTINCT tag FROM st_prov
                WHERE state = ?
                ORDER BY tag
                """,
                (geo_state,),
            )
        ]
        other_tags = [item for item in tags_in_state if item != tag]
        if not other_tags:
            continue
        foreign_provinces = sum(
            count_provinces_in_scope(conn, geo_state, other_tag)
            for other_tag in other_tags
        )
        if foreign_provinces == 0:
            continue
        own_provinces = count_provinces_in_scope(conn, geo_state, tag)
        total_foreign_provinces += foreign_provinces
        states.append(
            {
                "state": geo_state,
                "homelands": homelands,
                "own_provinces": own_provinces,
                "other_tags": other_tags,
                "foreign_provinces": foreign_provinces,
            }
        )

    return {
        "tag": tag,
        "primary_cultures": sorted(primary),
        "states": states,
        "state_count": len(states),
        "foreign_provinces": total_foreign_provinces,
    }


def acquire_all_homelands(conn: sqlite3.Connection, *, tag: str, on_progress: Callable[[int, str], None] | None = None) -> dict:
    """Transfer every foreign scope in primary-culture homelands worldwide to ``tag``."""
    with atomic_edit(conn):
        tag = str(tag)
        preview = load_acquire_homelands_preview(conn, tag, on_progress=on_progress)
        if not preview["states"]:
            raise ValueError("没有可获取的文化本土（无他国分属）")

        transfers: list[dict] = []
        annexed_tags: set[str] = set()
        states_touched: list[str] = []
        steps: list[tuple[str, object, object | None]] = []
        foreign_steps: list[tuple[str, object, object | None]] = []
        foreign_tags_captured: set[str] = set()

        transfer_plan: list[tuple[str, str]] = []
        for state_info in preview["states"]:
            state = str(state_info["state"])
            for other_tag in state_info["other_tags"]:
                if count_provinces_in_scope(conn, state, other_tag) == 0:
                    continue
                transfer_plan.append((state, str(other_tag)))

        tick = make_loop_progress(on_progress, len(transfer_plan), prefix="获取本土 ")

        for state_info in preview["states"]:
            state = str(state_info["state"])
            other_tags = list(state_info["other_tags"])
            if not other_tags:
                continue
            states_touched.append(state)
            scope_type_before = _scope_state_type(conn, state, tag)
            for other_tag in other_tags:
                if count_provinces_in_scope(conn, state, other_tag) == 0:
                    continue
                foreign_undo = None
                if (
                    other_tag not in foreign_tags_captured
                    and not tag_has_provinces_outside_state(conn, other_tag, state)
                ):
                    foreign_undo = foreign_ownership_undo(
                        other_tag,
                        capture_foreign_ownership_for_effective_owner(conn, other_tag),
                    )
                undo = capture_transfer_undo(
                    conn,
                    state=state,
                    origin_tag=other_tag,
                )
                result = transfer_state(
                    conn,
                    state=state,
                    origin_tag=other_tag,
                    new_tag=tag,
                    state_type="incorporated",
                    record_batch=False,
                )
                transfers.append(result)
                steps.append(("transfer_state", result, undo))
                tick(f"正在获取 {state}（← {other_tag}）")
                if result.get("annexed_source_tag") and foreign_undo is not None:
                    annexed_tags.add(other_tag)
                    foreign_tags_captured.add(other_tag)
                    foreign_steps.append(
                        (
                            "rewrite_foreign_ownership",
                            {
                                "from_tag": other_tag,
                                "to_tag": tag,
                                "count": int(
                                    result["cascade"]["annexation"][
                                        "foreign_ownership_updates"
                                    ]
                                ),
                            },
                            foreign_undo,
                        )
                    )
                elif result.get("annexed_source_tag"):
                    annexed_tags.add(other_tag)
            if scope_type_before is not None and scope_type_before != "incorporated":
                _apply_target_state_type(conn, state, tag, "incorporated")
                steps.append(
                    (
                        "change_state_type",
                        {
                            "op": "change_state_type",
                            "tag": tag,
                            "state": state,
                            "before": scope_type_before,
                            "after": "incorporated",
                        },
                        {"before": scope_type_before},
                    )
                )

        if not transfers:
            raise ValueError("没有可转移的地区")

        op = "acquire_all_homelands+annex" if annexed_tags else "acquire_all_homelands"
        payload = {
            "op": op,
            "tag": tag,
            "to_tag": tag,
            "primary_cultures": preview["primary_cultures"],
            "states_acquired": states_touched,
            "states_transferred": len(states_touched),
            "provinces_moved": sum(int(item["provinces_moved"]) for item in transfers),
            "annexed_tags": sorted(annexed_tags),
            "transfers": transfers,
        }
        note_annexed_tags(payload, annexed_tags)
        batch_id = write_batch(
            conn,
            summary=f"{op} {tag} ({len(states_touched)} states, {len(transfers)} transfers)",
            payload=payload,
            steps=[*steps, *foreign_steps],
        )
        payload["batch_id"] = batch_id
        return payload


def _owned_states_without_homeland(conn: sqlite3.Connection, tag: str) -> list[str]:
    return sorted(
        state
        for state in _geographic_states_owned(conn, tag)
        if not _geo_state_homelands(conn, state)
    )


def _removable_cultures_on_owned_territory(
    conn: sqlite3.Connection,
    tag: str,
) -> list[dict]:
    by_culture: dict[str, list[str]] = {}
    for state in _geographic_states_owned(conn, tag):
        for culture in _geo_state_homelands(conn, state):
            by_culture.setdefault(culture, []).append(state)
    return [
        {
            "culture": culture,
            "state_count": len(states),
            "states": sorted(states),
        }
        for culture, states in sorted(by_culture.items())
    ]


def load_homeland_batch_macro_preview(conn: sqlite3.Connection, tag: str) -> dict:
    tag = str(tag)
    if not tag_has_provinces(conn, tag):
        raise ValueError(f"{tag} 没有任何地块")
    owned_states = _geographic_states_owned(conn, tag)
    fillable_states = _owned_states_without_homeland(conn, tag)
    cultures = [
        str(row[0])
        for row in conn.execute("SELECT culture FROM ref_culture ORDER BY culture")
    ]
    return {
        "tag": tag,
        "owned_state_count": len(owned_states),
        "owned_states": owned_states,
        "removable_cultures": _removable_cultures_on_owned_territory(conn, tag),
        "fillable_state_count": len(fillable_states),
        "fillable_states": fillable_states,
        "cultures": cultures,
    }


def _apply_homeland_batch(
    conn: sqlite3.Connection,
    *,
    tag: str,
    culture: str,
    states: list[str],
    action: str,
    op_name: str,
    summary_prefix: str,
    empty_error: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    tag = str(tag)
    culture = _validate_culture(conn, culture)
    if action not in ("add", "remove"):
        raise ValueError("action 必须是 add 或 remove")

    candidates = sorted({str(state) for state in states})
    if not candidates:
        raise ValueError(empty_error)

    steps: list[tuple[str, dict, dict]] = []
    updated: list[str] = []
    tick = make_loop_progress(on_progress, len(candidates), prefix=summary_prefix)

    for state in candidates:
        _ensure_geo_state(conn, state)
        exists = culture in _geo_state_homelands(conn, state)
        if action == "add":
            if exists:
                tick(f"跳过 {state}（已有 {culture}）")
                continue
            conn.execute(
                "INSERT INTO geo_homeland (state, culture) VALUES (?, ?)",
                (state, culture),
            )
        else:
            if not exists:
                tick(f"跳过 {state}（无 {culture}）")
                continue
            conn.execute(
                "DELETE FROM geo_homeland WHERE state = ? AND culture = ?",
                (state, culture),
            )
        updated.append(state)
        step_result = {
            "op": "change_homeland",
            "state": state,
            "culture": culture,
            "action": action,
        }
        steps.append(
            (
                "change_homeland",
                step_result,
                capture_toggle_undo(
                    kind="change_homeland",
                    state=state,
                    key=culture,
                    key_name="culture",
                    action=action,
                ),
            )
        )
        tick(f"正在{summary_prefix}{state}")

    if not updated:
        raise ValueError(empty_error)

    payload = {
        "op": op_name,
        "tag": tag,
        "culture": culture,
        "action": action,
        "states_updated": updated,
        "state_count": len(updated),
    }
    batch_id = write_batch(
        conn,
        summary=f"{op_name} {tag} {culture} ({len(updated)} states)",
        payload=payload,
        steps=steps,
    )
    payload["batch_id"] = batch_id
    return payload


def batch_remove_homeland(
    conn: sqlite3.Connection,
    *,
    tag: str,
    culture: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Remove ``culture`` homeland from every geographic state owned by ``tag``."""
    with atomic_edit(conn):
        tag = str(tag)
        culture = _validate_culture(conn, culture)
        states = [
            state
            for state in _geographic_states_owned(conn, tag)
            if culture in _geo_state_homelands(conn, state)
        ]
        if not states:
            raise ValueError(f"{tag} 拥有的地区中没有 {culture} 文化本土")
        return _apply_homeland_batch(
            conn,
            tag=tag,
            culture=culture,
            states=states,
            action="remove",
            op_name="batch_remove_homeland",
            summary_prefix="删除文化本土 ",
            empty_error=f"{tag} 拥有的地区中没有 {culture} 文化本土",
            on_progress=on_progress,
        )


def batch_add_homeland(
    conn: sqlite3.Connection,
    *,
    tag: str,
    culture: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Add ``culture`` homeland to every geographic state owned by ``tag``."""
    with atomic_edit(conn):
        tag = str(tag)
        if not tag_has_provinces(conn, tag):
            raise ValueError(f"{tag} 没有任何地块")
        culture = _validate_culture(conn, culture)
        states = _geographic_states_owned(conn, tag)
        return _apply_homeland_batch(
            conn,
            tag=tag,
            culture=culture,
            states=states,
            action="add",
            op_name="batch_add_homeland",
            summary_prefix="添加文化本土 ",
            empty_error=f"{tag} 所有拥有地区已含 {culture} 文化本土",
            on_progress=on_progress,
        )


def batch_fill_homeland(
    conn: sqlite3.Connection,
    *,
    tag: str,
    culture: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Add ``culture`` homeland to owned states that currently have no homelands."""
    with atomic_edit(conn):
        tag = str(tag)
        culture = _validate_culture(conn, culture)
        states = _owned_states_without_homeland(conn, tag)
        if not states:
            raise ValueError(f"{tag} 没有无文化本土的拥有地区")
        return _apply_homeland_batch(
            conn,
            tag=tag,
            culture=culture,
            states=states,
            action="add",
            op_name="batch_fill_homeland",
            summary_prefix="填充文化本土 ",
            empty_error=f"{tag} 没有无文化本土的拥有地区",
            on_progress=on_progress,
        )


def _owned_states_for_homeland_scope(
    conn: sqlite3.Connection,
    tag: str,
    *,
    include_split: bool,
) -> list[str]:
    owned = _geographic_states_owned(conn, tag)
    if include_split:
        return owned
    split = set(list_split_states_for_tag(conn, tag))
    return [state for state in owned if state not in split]


def _homeland_clear_scope_summary(
    conn: sqlite3.Connection,
    states: list[str],
) -> dict:
    states_with = [state for state in states if _geo_state_homelands(conn, state)]
    homeland_count = sum(
        len(_geo_state_homelands(conn, state)) for state in states_with
    )
    return {
        "owned_state_count": len(states),
        "states_with_homelands": len(states_with),
        "homeland_entry_count": homeland_count,
        "states": states_with,
    }


def load_remove_all_homelands_preview(conn: sqlite3.Connection, tag: str) -> dict:
    tag = str(tag)
    if not tag_has_provinces(conn, tag):
        raise ValueError(f"{tag} 没有任何地块")
    owned = _geographic_states_owned(conn, tag)
    split = list_split_states_for_tag(conn, tag)
    exclusive = [state for state in owned if state not in set(split)]
    return {
        "tag": tag,
        "split_state_count": len(split),
        "include_split": _homeland_clear_scope_summary(conn, owned),
        "exclude_split": _homeland_clear_scope_summary(conn, exclusive),
    }


def batch_remove_all_homelands(
    conn: sqlite3.Connection,
    *,
    tag: str,
    include_split: bool,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict:
    """Remove every homeland from owned geographic states."""
    with atomic_edit(conn):
        tag = str(tag)
        if not tag_has_provinces(conn, tag):
            raise ValueError(f"{tag} 没有任何地块")
        states = _owned_states_for_homeland_scope(conn, tag, include_split=include_split)
        planned = [
            (state, culture)
            for state in states
            for culture in sorted(_geo_state_homelands(conn, state))
        ]
        if not planned:
            scope = "拥有地区" if include_split else "非分属拥有地区"
            raise ValueError(f"{tag} 的{scope}中没有文化本土可删")

        steps: list[tuple[str, dict, dict]] = []
        updated_states: list[str] = []
        seen_states: set[str] = set()
        tick = make_loop_progress(
            on_progress,
            len(planned),
            prefix="删除文化本土 ",
        )
        for state, culture in planned:
            conn.execute(
                "DELETE FROM geo_homeland WHERE state = ? AND culture = ?",
                (state, culture),
            )
            if state not in seen_states:
                seen_states.add(state)
                updated_states.append(state)
            step_result = {
                "op": "change_homeland",
                "state": state,
                "culture": culture,
                "action": "remove",
            }
            steps.append(
                (
                    "change_homeland",
                    step_result,
                    capture_toggle_undo(
                        kind="change_homeland",
                        state=state,
                        key=culture,
                        key_name="culture",
                        action="remove",
                    ),
                )
            )
            tick(f"正在删除 {state} {culture}")

        op = (
            "batch_remove_all_homelands"
            if include_split
            else "batch_remove_all_homelands_exclusive"
        )
        payload = {
            "op": op,
            "tag": tag,
            "include_split": include_split,
            "states_updated": updated_states,
            "state_count": len(updated_states),
            "homeland_removals": len(planned),
        }
        batch_id = write_batch(
            conn,
            summary=(
                f"{op} {tag} ({len(updated_states)} states, {len(planned)} entries)"
            ),
            payload=payload,
            steps=steps,
        )
        payload["batch_id"] = batch_id
        return payload
