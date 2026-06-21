"""Country-level batch pop culture / religion conversion."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from interactive_map.edit.atomic import atomic_edit
from interactive_map.edit.log import write_batch
from interactive_map.edit.pops import _load_pop_row, _validate_culture, _validate_religion
from interactive_map.edit.snapshot import _load_pop_snapshot
from interactive_map.edit.transfer import tag_has_provinces
from interactive_map.macro_edit_job import make_loop_progress

RELIGION_DEFAULT_SENTINEL = "__culture_default__"

POP_INVALIDATE_LAYERS = (
    "slavery",
    "pop_total",
    "pop_culture",
    "pop_religion",
)


def normalize_religion_param(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == RELIGION_DEFAULT_SENTINEL:
        return None
    return text


def religion_param_key(religion: str | None) -> str:
    return RELIGION_DEFAULT_SENTINEL if religion is None else str(religion)


def _load_tag_pops(conn: sqlite3.Connection, tag: str) -> list[dict[str, Any]]:
    return [
        _load_pop_row(conn, int(row[0]))
        for row in conn.execute(
            "SELECT id FROM st_pop WHERE tag = ? ORDER BY state, id",
            (tag,),
        )
    ]


def _summarize_cultures(pops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_culture: dict[str, dict[str, Any]] = {}
    for pop in pops:
        culture = str(pop["culture"])
        entry = by_culture.setdefault(
            culture,
            {"culture": culture, "pop_count": 0, "total_size": 0, "scope_count": set()},
        )
        entry["pop_count"] += 1
        entry["total_size"] += int(pop["size"])
        entry["scope_count"].add((str(pop["state"]), str(pop["tag"])))
    out = []
    for culture in sorted(by_culture):
        item = by_culture[culture]
        out.append(
            {
                "culture": culture,
                "pop_count": item["pop_count"],
                "total_size": item["total_size"],
                "scope_count": len(item["scope_count"]),
            }
        )
    return out


def _summarize_religions(pops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_religion: dict[str | None, dict[str, Any]] = {}
    for pop in pops:
        religion = pop["religion"]
        entry = by_religion.setdefault(
            religion,
            {
                "religion": religion,
                "religion_key": religion_param_key(religion),
                "pop_count": 0,
                "total_size": 0,
                "scope_count": set(),
            },
        )
        entry["pop_count"] += 1
        entry["total_size"] += int(pop["size"])
        entry["scope_count"].add((str(pop["state"]), str(pop["tag"])))
    out = []
    for religion in sorted(by_religion, key=lambda r: (r is not None, r or "")):
        item = by_religion[religion]
        out.append(
            {
                "religion": item["religion"],
                "religion_key": item["religion_key"],
                "pop_count": item["pop_count"],
                "total_size": item["total_size"],
                "scope_count": len(item["scope_count"]),
            }
        )
    return out


def load_pop_convert_macro_preview(conn: sqlite3.Connection, tag: str) -> dict[str, Any]:
    tag = str(tag)
    if not tag_has_provinces(conn, tag):
        raise ValueError(f"{tag} 没有任何地块")
    pops = _load_tag_pops(conn, tag)
    all_cultures = [
        str(row[0])
        for row in conn.execute("SELECT culture FROM ref_culture ORDER BY culture")
    ]
    all_religions = [
        {
            "religion": None,
            "religion_key": RELIGION_DEFAULT_SENTINEL,
        },
        *(
            {"religion": str(row[0]), "religion_key": str(row[0])}
            for row in conn.execute("SELECT religion FROM ref_religion ORDER BY religion")
        ),
    ]
    return {
        "tag": tag,
        "convertible_cultures": _summarize_cultures(pops),
        "all_cultures": all_cultures,
        "convertible_religions": _summarize_religions(pops),
        "all_religions": all_religions,
    }


def _pops_matching_target_key(
    conn: sqlite3.Connection,
    *,
    state: str,
    tag: str,
    culture: str,
    religion: str | None,
    is_slaves: bool,
    exclude_ids: set[int],
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id FROM st_pop
        WHERE state = ? AND tag = ? AND culture = ?
          AND IFNULL(religion, '') = IFNULL(?, '')
          AND is_slaves = ?
        ORDER BY id
        """,
        (state, tag, culture, religion, int(is_slaves)),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for pop_id, in rows:
        pop_id = int(pop_id)
        if pop_id in exclude_ids:
            continue
        out.append(_load_pop_row(conn, pop_id))
    return out


def _apply_grouped_pop_conversion(
    conn: sqlite3.Connection,
    groups: dict[tuple[Any, ...], list[dict[str, Any]]],
    *,
    update_fields: Callable[[dict[str, Any]], tuple[str, str | None]],
    on_progress: Callable[[int, str], None] | None,
    progress_prefix: str,
) -> tuple[list[tuple[str, dict, dict]], dict[str, int]]:
    steps: list[tuple[str, dict, dict]] = []
    stats = {"groups": 0, "updated": 0, "merged": 0, "deleted": 0}
    tick = make_loop_progress(on_progress, len(groups), prefix=progress_prefix)
    processed_ids: set[int] = set()

    for key, pops in sorted(groups.items()):
        state, tag, culture, religion, is_slaves = key
        source_ids = {int(pop["id"]) for pop in pops}
        if source_ids & processed_ids:
            continue
        existing_targets = _pops_matching_target_key(
            conn,
            state=state,
            tag=tag,
            culture=culture,
            religion=religion,
            is_slaves=bool(is_slaves),
            exclude_ids=source_ids | processed_ids,
        )
        all_pops = pops + existing_targets
        pop_ids = {int(pop["id"]) for pop in all_pops}
        total_size = sum(int(pop["size"]) for pop in all_pops)

        needs_field_update = any(
            str(pop["culture"]) != culture or pop["religion"] != religion for pop in pops
        )

        if len(all_pops) == 1 and not needs_field_update:
            processed_ids.update(pop_ids)
            stats["groups"] += 1
            tick(f"{state}/{tag}")
            continue

        keep_id = min(pop_ids)
        new_culture, new_religion = update_fields(pops[0])
        before_keep = _load_pop_snapshot(conn, keep_id)
        conn.execute(
            """
            UPDATE st_pop
            SET culture = ?, religion = ?, size = ?
            WHERE id = ?
            """,
            (new_culture, new_religion, total_size, keep_id),
        )
        after_keep = _load_pop_snapshot(conn, keep_id)
        steps.append(("update_pop", after_keep, before_keep))
        stats["updated"] += 1
        if len(all_pops) > 1:
            stats["merged"] += len(all_pops) - 1
        for pop in all_pops:
            pop_id = int(pop["id"])
            if pop_id == keep_id:
                continue
            before = _load_pop_snapshot(conn, pop_id)
            conn.execute("DELETE FROM st_pop WHERE id = ?", (pop_id,))
            steps.append(("delete_pop", {"pop_id": pop_id}, before))
            stats["deleted"] += 1

        processed_ids.update(pop_ids)
        stats["groups"] += 1
        tick(f"{state}/{tag}")

    return steps, stats


def batch_convert_culture(
    conn: sqlite3.Connection,
    *,
    tag: str,
    from_culture: str,
    to_culture: str,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    with atomic_edit(conn):
        tag = str(tag)
        from_culture = _validate_culture(conn, from_culture)
        to_culture = _validate_culture(conn, to_culture)
        if from_culture == to_culture:
            raise ValueError("新文化必须不同于原文化")
        if not tag_has_provinces(conn, tag):
            raise ValueError(f"{tag} 没有任何地块")

        source_pops = [
            pop
            for pop in _load_tag_pops(conn, tag)
            if pop["culture"] == from_culture
        ]
        if not source_pops:
            raise ValueError(f"{tag} 没有 {from_culture} 文化人口")

        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for pop in source_pops:
            key = (
                str(pop["state"]),
                str(pop["tag"]),
                to_culture,
                pop["religion"],
                bool(pop["is_slaves"]),
            )
            groups[key].append(pop)

        steps, stats = _apply_grouped_pop_conversion(
            conn,
            groups,
            update_fields=lambda _pop: (to_culture, _pop["religion"]),
            on_progress=on_progress,
            progress_prefix="转化文化 ",
        )
        if not steps:
            raise ValueError("没有人口被转化")

        payload = {
            "op": "batch_convert_culture",
            "tag": tag,
            "from_culture": from_culture,
            "to_culture": to_culture,
            "pop_entries": len(source_pops),
            "groups": stats["groups"],
            "invalidate_layers": POP_INVALIDATE_LAYERS,
        }
        batch_id = write_batch(
            conn,
            summary=(
                f"batch_convert_culture {tag} {from_culture}->{to_culture} "
                f"({len(source_pops)} entries)"
            ),
            payload=payload,
            steps=steps,
        )
        payload["batch_id"] = batch_id
        return payload


def batch_convert_religion(
    conn: sqlite3.Connection,
    *,
    tag: str,
    from_religion: str | None,
    to_religion: str | None,
    on_progress: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    with atomic_edit(conn):
        tag = str(tag)
        from_religion = _validate_religion(conn, from_religion)
        to_religion = _validate_religion(conn, to_religion)
        if from_religion == to_religion:
            raise ValueError("新宗教必须不同于原宗教")
        if not tag_has_provinces(conn, tag):
            raise ValueError(f"{tag} 没有任何地块")

        source_pops = [
            pop
            for pop in _load_tag_pops(conn, tag)
            if pop["religion"] == from_religion
        ]
        if not source_pops:
            label = "文化默认宗教" if from_religion is None else from_religion
            raise ValueError(f"{tag} 没有 {label} 人口")

        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for pop in source_pops:
            key = (
                str(pop["state"]),
                str(pop["tag"]),
                str(pop["culture"]),
                to_religion,
                bool(pop["is_slaves"]),
            )
            groups[key].append(pop)

        steps, stats = _apply_grouped_pop_conversion(
            conn,
            groups,
            update_fields=lambda pop: (str(pop["culture"]), to_religion),
            on_progress=on_progress,
            progress_prefix="转化宗教 ",
        )
        if not steps:
            raise ValueError("没有人口被转化")

        payload = {
            "op": "batch_convert_religion",
            "tag": tag,
            "from_religion": from_religion,
            "to_religion": to_religion,
            "from_religion_key": religion_param_key(from_religion),
            "to_religion_key": religion_param_key(to_religion),
            "pop_entries": len(source_pops),
            "groups": stats["groups"],
            "invalidate_layers": POP_INVALIDATE_LAYERS,
        }
        batch_id = write_batch(
            conn,
            summary=(
                f"batch_convert_religion {tag} "
                f"{religion_param_key(from_religion)}->{religion_param_key(to_religion)} "
                f"({len(source_pops)} entries)"
            ),
            payload=payload,
            steps=steps,
        )
        payload["batch_id"] = batch_id
        return payload
