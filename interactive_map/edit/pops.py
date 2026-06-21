"""Population write operations and form options."""

from __future__ import annotations

import re
import sqlite3

from interactive_map.edit.log import write_batch

POP_SIZE_ERROR = "人口数量必须是大于 0 的整数"


def validate_pop_size(size: int) -> int:
    if isinstance(size, bool) or not isinstance(size, int):
        raise ValueError(POP_SIZE_ERROR)
    if size < 1:
        raise ValueError(POP_SIZE_ERROR)
    return size


def parse_pop_size(raw: object, *, default: int = 1000) -> int:
    if raw is None:
        return validate_pop_size(default)
    if isinstance(raw, bool):
        raise ValueError(POP_SIZE_ERROR)
    if isinstance(raw, int):
        return validate_pop_size(raw)
    if isinstance(raw, float):
        if not raw.is_integer():
            raise ValueError(POP_SIZE_ERROR)
        return validate_pop_size(int(raw))
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return validate_pop_size(default)
        if re.fullmatch(r"-?\d+", text):
            return validate_pop_size(int(text))
        raise ValueError(POP_SIZE_ERROR)
    raise ValueError(POP_SIZE_ERROR)


def normalize_religion(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def normalize_is_slaves(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, int):
        return bool(raw)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off", ""):
            return False
    raise ValueError("is_slaves 必须是布尔值")


def _require_scope(conn: sqlite3.Connection, tag: str, state: str) -> None:
    row = conn.execute(
        "SELECT 1 FROM st WHERE tag = ? AND state = ?", (tag, state)
    ).fetchone()
    if row is None:
        raise ValueError(f"scope state 不存在：{tag}/{state}")


def _validate_culture(conn: sqlite3.Connection, culture: str) -> str:
    culture = str(culture).strip()
    if not culture:
        raise ValueError("需要 culture")
    row = conn.execute(
        "SELECT 1 FROM ref_culture WHERE culture = ?", (culture,)
    ).fetchone()
    if row is None:
        raise ValueError(f"未知文化：{culture}")
    return culture


def _validate_religion(conn: sqlite3.Connection, religion: str | None) -> str | None:
    religion = normalize_religion(religion)
    if religion is None:
        return None
    row = conn.execute(
        "SELECT 1 FROM ref_religion WHERE religion = ?", (religion,)
    ).fetchone()
    if row is None:
        raise ValueError(f"未知宗教：{religion}")
    return religion


def _load_pop_row(conn: sqlite3.Connection, pop_id: int) -> dict:
    row = conn.execute(
        """
        SELECT id, state, tag, culture, religion, is_slaves, size
        FROM st_pop
        WHERE id = ?
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


def _pop_conflict(
    conn: sqlite3.Connection,
    *,
    state: str,
    tag: str,
    culture: str,
    religion: str | None,
    is_slaves: bool,
    exclude_id: int | None = None,
) -> None:
    params: list[object] = [state, tag, culture, religion, int(is_slaves)]
    sql = """
        SELECT id FROM st_pop
        WHERE state = ? AND tag = ? AND culture = ?
          AND IFNULL(religion, '') = IFNULL(?, '')
          AND is_slaves = ?
    """
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(exclude_id)
    row = conn.execute(sql, params).fetchone()
    if row is not None:
        raise ValueError("已存在相同文化/宗教/奴隶类型的人口条目")


def _insert_pop(
    conn: sqlite3.Connection,
    *,
    state: str,
    tag: str,
    culture: str,
    religion: str | None,
    is_slaves: bool,
    size: int,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO st_pop (state, tag, culture, religion, is_slaves, size)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (state, tag, culture, religion, int(is_slaves), size),
    )
    return int(cur.lastrowid)


def _delete_pop_row(conn: sqlite3.Connection, pop_id: int) -> dict:
    snapshot = _load_pop_row(conn, pop_id)
    conn.execute("DELETE FROM st_pop WHERE id = ?", (pop_id,))
    return snapshot


def load_pop_options(conn: sqlite3.Connection, tag: str, state: str) -> dict:
    _require_scope(conn, tag, state)
    cultures = [
        str(row[0])
        for row in conn.execute("SELECT culture FROM ref_culture ORDER BY culture")
    ]
    religions = [
        str(row[0])
        for row in conn.execute("SELECT religion FROM ref_religion ORDER BY religion")
    ]
    homelands = [
        str(row[0])
        for row in conn.execute(
            "SELECT culture FROM geo_homeland WHERE state = ? ORDER BY culture",
            (state,),
        )
    ]
    default_culture = homelands[0] if homelands else (cultures[0] if cultures else "")
    return {
        "tag": tag,
        "state": state,
        "cultures": cultures,
        "religions": religions,
        "defaults": {
            "culture": default_culture,
            "religion": "",
            "is_slaves": False,
            "size": 1000,
        },
    }


def add_pop(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    culture: str,
    religion: str | None = "",
    is_slaves: bool = False,
    size: int = 1000,
) -> dict:
    _require_scope(conn, tag, state)
    culture = _validate_culture(conn, culture)
    religion = _validate_religion(conn, religion)
    is_slaves = normalize_is_slaves(is_slaves)
    size = validate_pop_size(size)
    _pop_conflict(
        conn,
        state=state,
        tag=tag,
        culture=culture,
        religion=religion,
        is_slaves=is_slaves,
    )
    pop_id = _insert_pop(
        conn,
        state=state,
        tag=tag,
        culture=culture,
        religion=religion,
        is_slaves=is_slaves,
        size=size,
    )
    after = _load_pop_row(conn, pop_id)
    batch_id = write_batch(
        conn,
        summary=f"create_pop {tag}/{state}/{culture}",
        payload={"op": "add_pop", "tag": tag, "state": state, "culture": culture},
        steps=[("create_pop", after, {"delete_pop_id": pop_id})],
    )
    return {"batch_id": batch_id, "pop_id": pop_id, "pop": after}


def delete_pop(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    pop_id: int,
) -> dict:
    _require_scope(conn, tag, state)
    row = _load_pop_row(conn, pop_id)
    if row["tag"] != tag or row["state"] != state:
        raise ValueError("人口不在当前 scope state")
    snapshot = _delete_pop_row(conn, pop_id)
    batch_id = write_batch(
        conn,
        summary=f"delete_pop {tag}/{state}/{snapshot['culture']} id={pop_id}",
        payload={"op": "delete_pop", "pop_id": pop_id},
        steps=[("delete_pop", {"pop_id": pop_id}, snapshot)],
    )
    return {"batch_id": batch_id, "deleted": snapshot}


def update_pop(
    conn: sqlite3.Connection,
    *,
    tag: str,
    state: str,
    pop_id: int,
    culture: str,
    religion: str | None = "",
    is_slaves: bool = False,
    size: int = 1000,
) -> dict:
    _require_scope(conn, tag, state)
    before = _load_pop_row(conn, pop_id)
    if before["tag"] != tag or before["state"] != state:
        raise ValueError("人口不在当前 scope state")
    culture = _validate_culture(conn, culture)
    religion = _validate_religion(conn, religion)
    is_slaves = normalize_is_slaves(is_slaves)
    size = validate_pop_size(size)
    _pop_conflict(
        conn,
        state=state,
        tag=tag,
        culture=culture,
        religion=religion,
        is_slaves=is_slaves,
        exclude_id=pop_id,
    )
    conn.execute(
        """
        UPDATE st_pop
        SET culture = ?, religion = ?, is_slaves = ?, size = ?
        WHERE id = ?
        """,
        (culture, religion, int(is_slaves), size, pop_id),
    )
    after = _load_pop_row(conn, pop_id)
    batch_id = write_batch(
        conn,
        summary=f"update_pop {tag}/{state}/{culture} id={pop_id}",
        payload={"op": "update_pop", "pop_id": pop_id},
        steps=[("update_pop", after, before)],
    )
    return {"batch_id": batch_id, "pop_id": pop_id, "pop": after}
