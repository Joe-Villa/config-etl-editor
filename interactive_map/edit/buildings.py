"""Building write operations and form options."""

from __future__ import annotations

import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pm_defaults import first_pm_for_group  # noqa: E402

from interactive_map.edit.log import write_batch  # noqa: E402


BASIC_OWNERSHIP_TYPES: tuple[dict[str, str], ...] = (
    {"value": "financial_district", "label": "金融区"},
    {"value": "manor_house", "label": "庄园宅邸"},
    {"value": "self", "label": "自有"},
    {"value": "country", "label": "国有"},
)
DEFAULT_OWNERSHIP_TYPE = "country"
BUILDING_LEVEL_ERROR = "建筑等级必须是大于等于 1 的整数"


def validate_building_level(level: int) -> int:
    if isinstance(level, bool) or not isinstance(level, int):
        raise ValueError(BUILDING_LEVEL_ERROR)
    if level < 1:
        raise ValueError(BUILDING_LEVEL_ERROR)
    return level


def parse_building_level(raw: object, *, default: int = 1) -> int:
    if raw is None:
        return validate_building_level(default)
    if isinstance(raw, bool):
        raise ValueError(BUILDING_LEVEL_ERROR)
    if isinstance(raw, int):
        return validate_building_level(raw)
    if isinstance(raw, float):
        if not raw.is_integer():
            raise ValueError(BUILDING_LEVEL_ERROR)
        return validate_building_level(int(raw))
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return validate_building_level(default)
        if re.fullmatch(r"-?\d+", text):
            return validate_building_level(int(text))
        raise ValueError(BUILDING_LEVEL_ERROR)
    raise ValueError(BUILDING_LEVEL_ERROR)


@dataclass(frozen=True)
class OwnershipSlice:
    ownership: str
    level: int
    owner_tag: str
    owner_state: str


def _require_scope(conn: sqlite3.Connection, tag: str, state: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM st WHERE tag = ? AND state = ?", (tag, state)
    ).fetchone()
    if row is None:
        raise ValueError(f"scope state 不存在：{tag}/{state}")


def _pm_index(conn: sqlite3.Connection) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    pm_by_pmg: dict[str, list[str]] = {}
    for pmg, pm, _ord in conn.execute(
        "SELECT pm_group, pm, ord FROM ref_pmg_pm ORDER BY pm_group, ord"
    ):
        pm_by_pmg.setdefault(pmg, []).append(pm)
    building_pmgs: dict[str, list[str]] = {}
    for building, pmg, _ord in conn.execute(
        "SELECT building, pm_group, ord FROM ref_bld_pmg ORDER BY building, ord"
    ):
        building_pmgs.setdefault(building, []).append(pmg)
    return pm_by_pmg, building_pmgs


def first_pms_for_building(conn: sqlite3.Connection, building: str) -> list[str]:
    pm_by_pmg, building_pmgs = _pm_index(conn)
    result: list[str] = []
    for pmg in building_pmgs.get(building, []):
        pms = pm_by_pmg.get(pmg, [])
        if not pms:
            continue
        fallback = first_pm_for_group(pms)
        assert fallback is not None
        result.append(fallback)
    return result


def normalize_pms(
    conn: sqlite3.Connection, building: str, pms: list[str] | None
) -> list[str]:
    pm_by_pmg, building_pmgs = _pm_index(conn)
    expected = building_pmgs.get(building, [])
    if not expected:
        return list(pms or [])
    chosen: dict[str, str] = {}
    for pm in pms or []:
        for pmg in expected:
            row = conn.execute(
                "SELECT 1 FROM ref_pmg_pm WHERE pm_group = ? AND pm = ?",
                (pmg, pm),
            ).fetchone()
            if row:
                chosen[pmg] = pm
                break
    result: list[str] = []
    for pmg in expected:
        if pmg in chosen:
            result.append(chosen[pmg])
            continue
        pms_in_group = pm_by_pmg.get(pmg, [])
        if not pms_in_group:
            continue
        fallback = first_pm_for_group(pms_in_group)
        assert fallback is not None
        result.append(fallback)
    return result


def _load_active_tags(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT DISTINCT tag FROM st_prov ORDER BY tag")
    }


def _validate_owner_tag(
    conn: sqlite3.Connection,
    scope_tag: str,
    ownership_type: str,
    owner_tag: str,
) -> None:
    if ownership_type.strip() == "self":
        return
    active = _load_active_tags(conn)
    effective = owner_tag.strip() or scope_tag
    if effective not in active:
        raise ValueError(f"owner_tag 必须是拥有至少一块地区的 tag：{effective}")


def _normalize_ownership_for_scope(
    tag: str,
    state: str,
    ownership_type: str,
    owner_tag: str,
    owner_state: str,
) -> OwnershipSlice:
    ownership = ownership_type.strip()
    otag = owner_tag.strip()
    ostate = owner_state.strip()
    if ownership == "self":
        otag = ""
        ostate = ""
    elif ownership == "country":
        ostate = ""
    # Empty owner_tag / owner_state means "follow current scope tag/state" in DB/UI.
    # Export must use resolve_owner_tag_for_export / resolve_owner_state_for_export instead.
    if not otag or otag == tag:
        otag = ""
    if not ostate or ostate == state:
        ostate = ""
    return OwnershipSlice(
        ownership=ownership,
        level=1,
        owner_tag=otag,
        owner_state=ostate,
    )


def resolve_owner_tag_for_export(scope_tag: str, owner_tag: str) -> str:
    tag = owner_tag.strip()
    return tag or scope_tag


def resolve_owner_state_for_export(scope_state: str, owner_state: str) -> str:
    state = owner_state.strip()
    return state or scope_state


def _load_building_row(conn: sqlite3.Connection, bld_id: int) -> dict:
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


def _insert_building(
    conn: sqlite3.Connection,
    *,
    state: str,
    tag: str,
    building: str,
    pms: list[str],
    ownership: OwnershipSlice,
    level: int | None = None,
) -> int:
    exists = conn.execute(
        "SELECT buildable FROM ref_bld WHERE building = ?", (building,)
    ).fetchone()
    if not exists:
        raise ValueError(f"未知建筑：{building}")
    if not int(exists[0]):
        raise ValueError(f"建筑不可建造：{building}")
    cur = conn.execute(
        "INSERT INTO st_bld (state, tag, building, reserves) VALUES (?, ?, ?, 1)",
        (state, tag, building),
    )
    bld_id = int(cur.lastrowid)
    resolved_level = (
        validate_building_level(level)
        if level is not None
        else validate_building_level(ownership.level)
    )
    own = OwnershipSlice(
        ownership=ownership.ownership,
        level=resolved_level,
        owner_tag=ownership.owner_tag,
        owner_state=ownership.owner_state,
    )
    conn.execute(
        """
        INSERT INTO st_bld_own (bld_id, ord, ownership, level, owner_tag, owner_state)
        VALUES (?, 0, ?, ?, ?, ?)
        """,
        (bld_id, own.ownership, own.level, own.owner_tag, own.owner_state),
    )
    for ord_, pm in enumerate(pms):
        conn.execute(
            "INSERT INTO st_bld_pm (bld_id, ord, pm) VALUES (?, ?, ?)",
            (bld_id, ord_, pm),
        )
    return bld_id


def _delete_building_row(conn: sqlite3.Connection, bld_id: int) -> dict:
    snapshot = _load_building_row(conn, bld_id)
    conn.execute("DELETE FROM st_bld WHERE id = ?", (bld_id,))
    return snapshot


def _replace_building_fields(
    conn: sqlite3.Connection,
    bld_id: int,
    *,
    pms: list[str],
    ownership: OwnershipSlice,
    level: int,
) -> None:
    level = validate_building_level(level)
    conn.execute("DELETE FROM st_bld_pm WHERE bld_id = ?", (bld_id,))
    conn.execute("DELETE FROM st_bld_own WHERE bld_id = ?", (bld_id,))
    conn.execute(
        """
        INSERT INTO st_bld_own (bld_id, ord, ownership, level, owner_tag, owner_state)
        VALUES (?, 0, ?, ?, ?, ?)
        """,
        (bld_id, ownership.ownership, level, ownership.owner_tag, ownership.owner_state),
    )
    for ord_, pm in enumerate(pms):
        conn.execute(
            "INSERT INTO st_bld_pm (bld_id, ord, pm) VALUES (?, ?, ?)",
            (bld_id, ord_, pm),
        )


def load_building_options(
    conn: sqlite3.Connection,
    tag: str,
    state: str,
    *,
    building: str | None = None,
) -> dict:
    _require_scope(conn, tag, state)
    building_groups: list[dict] = []
    for bg_row in conn.execute(
        """
        SELECT bg.root_group
        FROM ref_bld b
        JOIN ref_bg bg ON b.building_group = bg.building_group
        WHERE b.buildable = 1
        GROUP BY bg.root_group
        ORDER BY bg.root_group
        """
    ):
        root = str(bg_row[0])
        buildings_in_group = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT b.building
                FROM ref_bld b
                JOIN ref_bg bg ON b.building_group = bg.building_group
                WHERE b.buildable = 1 AND bg.root_group = ?
                ORDER BY b.building
                """,
                (root,),
            )
        ]
        if buildings_in_group:
            building_groups.append(
                {"building_group": root, "buildings": buildings_in_group}
            )
    buildings = [b for group in building_groups for b in group["buildings"]]
    building_group_map = {
        str(building): str(building_group)
        for building, building_group in conn.execute(
            """
            SELECT building, building_group
            FROM ref_bld
            WHERE buildable = 1
            ORDER BY building
            """
        )
    }
    tags = sorted(_load_active_tags(conn))
    states = [
        str(row[0]) for row in conn.execute("SELECT state FROM ref_sr ORDER BY state")
    ]
    companies = [
        str(row[0])
        for row in conn.execute("SELECT company_type FROM ref_co ORDER BY company_type")
    ]
    ownership_types = [dict(item) for item in BASIC_OWNERSHIP_TYPES]
    for company in companies:
        ownership_types.append({"value": company, "label": company})

    pm_groups: list[dict] = []
    first_pms: list[str] = []
    if building:
        pm_by_pmg, building_pmgs = _pm_index(conn)
        for pmg in building_pmgs.get(building, []):
            pms = pm_by_pmg.get(pmg, [])
            first_pm = first_pm_for_group(pms) if pms else None
            pm_groups.append(
                {
                    "pm_group": pmg,
                    "pms": pms,
                    "first_pm": first_pm,
                }
            )
            if first_pm:
                first_pms.append(first_pm)

    return {
        "tag": tag,
        "state": state,
        "buildings": buildings,
        "building_groups": building_groups,
        "building_group_map": building_group_map,
        "tags": tags,
        "states": states,
        "ownership_types": ownership_types,
        "pm_groups": pm_groups,
        "first_pms": first_pms,
        "defaults": {
            "level": 1,
            "ownership_type": DEFAULT_OWNERSHIP_TYPE,
            "owner_tag": "",
            "owner_state": "",
            "pms": first_pms,
        },
    }


def add_building(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    building: str,
    pms: list[str] | None,
    level: int = 1,
    ownership_type: str = DEFAULT_OWNERSHIP_TYPE,
    owner_tag: str = "",
    owner_state: str = "",
) -> dict:
    if not building:
        raise ValueError("需要 building_key")
    level = validate_building_level(level)
    _require_scope(conn, tag, state)
    normalized_pms = normalize_pms(conn, building, pms)
    ownership = _normalize_ownership_for_scope(
        tag, state, ownership_type, owner_tag, owner_state
    )
    ownership = OwnershipSlice(
        ownership=ownership.ownership,
        level=level,
        owner_tag=ownership.owner_tag,
        owner_state=ownership.owner_state,
    )
    _validate_owner_tag(conn, tag, ownership.ownership, ownership.owner_tag)
    bld_id = _insert_building(
        conn,
        state=state,
        tag=tag,
        building=building,
        pms=normalized_pms,
        ownership=ownership,
    )
    after = _load_building_row(conn, bld_id)
    batch_id = write_batch(
        conn,
        summary=f"create_building {tag}/{state}/{building}",
        payload={"op": "add_building", "tag": tag, "state": state, "building": building},
        steps=[
            (
                "create_building",
                after,
                {"delete_bld_id": bld_id},
            ),
        ],
    )
    return {"batch_id": batch_id, "bld_id": bld_id, "building": after}


def delete_building(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    bld_id: int,
) -> dict:
    _require_scope(conn, tag, state)
    row = _load_building_row(conn, bld_id)
    if row["tag"] != tag or row["state"] != state:
        raise ValueError("建筑不在当前 scope state")
    snapshot = _delete_building_row(conn, bld_id)
    batch_id = write_batch(
        conn,
        summary=f"delete_building {tag}/{state}/{snapshot['building']} id={bld_id}",
        payload={"op": "delete_building", "bld_id": bld_id},
        steps=[
            (
                "delete_building",
                {"bld_id": bld_id},
                snapshot,
            ),
        ],
    )
    return {"batch_id": batch_id, "deleted": snapshot}


def update_building(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    bld_id: int,
    pms: list[str] | None,
    level: int = 1,
    ownership_type: str = DEFAULT_OWNERSHIP_TYPE,
    owner_tag: str = "",
    owner_state: str = "",
    sync_pm_same_key: bool = True,
) -> dict:
    _require_scope(conn, tag, state)
    level = validate_building_level(level)
    before = _load_building_row(conn, bld_id)
    if before["tag"] != tag or before["state"] != state:
        raise ValueError("建筑不在当前 scope state")
    building_key = before["building"]
    normalized_pms = normalize_pms(conn, building_key, pms)
    ownership = _normalize_ownership_for_scope(
        tag, state, ownership_type, owner_tag, owner_state
    )
    ownership = OwnershipSlice(
        ownership=ownership.ownership,
        level=level,
        owner_tag=ownership.owner_tag,
        owner_state=ownership.owner_state,
    )
    _validate_owner_tag(conn, tag, ownership.ownership, ownership.owner_tag)

    targets = [bld_id]
    if sync_pm_same_key:
        targets = [
            int(row[0])
            for row in conn.execute(
                """
                SELECT id FROM st_bld
                WHERE tag = ? AND state = ? AND building = ?
                ORDER BY id
                """,
                (tag, state, building_key),
            )
        ]

    steps: list[tuple[str, object, object | None]] = []
    updated_ids: list[int] = []
    for target_id in targets:
        snap_before = _load_building_row(conn, target_id)
        if target_id == bld_id:
            _replace_building_fields(
                conn, target_id, pms=normalized_pms, ownership=ownership, level=level
            )
        elif sync_pm_same_key:
            own = snap_before["ownerships"][0] if snap_before["ownerships"] else {}
            _replace_building_fields(
                conn,
                target_id,
                pms=normalized_pms,
                ownership=OwnershipSlice(
                    ownership=str(own.get("ownership", "country")),
                    level=int(own.get("level", 1)),
                    owner_tag=str(own.get("owner_tag", "")),
                    owner_state=str(own.get("owner_state", "")),
                ),
                level=int(own.get("level", 1)),
            )
        updated_ids.append(target_id)
        steps.append(
            (
                "update_building",
                {"bld_id": target_id, "after": _load_building_row(conn, target_id)},
                snap_before,
            )
        )

    batch_id = write_batch(
        conn,
        summary=f"update_building {tag}/{state}/{building_key} id={bld_id}",
        payload={
            "op": "update_building",
            "bld_id": bld_id,
            "sync_pm_same_key": sync_pm_same_key,
        },
        steps=steps,
    )
    return {
        "batch_id": batch_id,
        "bld_id": bld_id,
        "updated_ids": updated_ids,
        "building": _load_building_row(conn, bld_id),
    }
