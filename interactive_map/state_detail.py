"""Load full tag+state detail from map_editor.sqlite for the editor panel."""

from __future__ import annotations

import sqlite3


HUB_TYPES = ("city", "port", "farm", "mine", "wood")


def _province_to_hex(province: str) -> str:
    value = str(province).strip().upper()
    if value.startswith("X"):
        value = value[1:]
    return f"#{value.lower()}"


def _load_state_hubs(conn: sqlite3.Connection, state: str) -> list[dict[str, str]]:
    row = conn.execute(
        "SELECT city, port, farm, mine, wood FROM ref_sr WHERE state = ?",
        (state,),
    ).fetchone()
    if row is None:
        return []
    hubs: list[dict[str, str]] = []
    for hub_type, province in zip(HUB_TYPES, row, strict=True):
        raw = str(province or "").strip()
        if raw:
            hubs.append({"hub_type": hub_type, "province": _province_to_hex(raw)})
    return hubs


def load_state_detail_json(
    conn: sqlite3.Connection,
    tag: str,
    state: str,
) -> dict | None:
    """Return detail for one tag+state row, or None if not in st."""
    tag = str(tag)
    state = str(state)
    row = conn.execute(
        "SELECT state_type FROM st WHERE tag = ? AND state = ?",
        (tag, state),
    ).fetchone()
    if row is None:
        return None

    homelands = [
        str(culture)
        for (culture,) in conn.execute(
            "SELECT culture FROM geo_homeland WHERE state = ? ORDER BY culture",
            (state,),
        )
    ]
    claims = [
        str(claim_tag)
        for (claim_tag,) in conn.execute(
            "SELECT claim_tag FROM geo_claim WHERE state = ? ORDER BY claim_tag",
            (state,),
        )
    ]
    provinces = [
        _province_to_hex(province)
        for (province,) in conn.execute(
            """
            SELECT province FROM st_prov
            WHERE tag = ? AND state = ?
            ORDER BY province
            """,
            (tag, state),
        )
    ]

    buildings: list[dict] = []
    for bld_id, building, reserves in conn.execute(
        """
        SELECT id, building, reserves
        FROM st_bld
        WHERE tag = ? AND state = ?
        ORDER BY building, id
        """,
        (tag, state),
    ):
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
                FROM st_bld_own
                WHERE bld_id = ?
                ORDER BY ord
                """,
                (bld_id,),
            )
        ]
        pms = [
            str(pm)
            for (pm,) in conn.execute(
                "SELECT pm FROM st_bld_pm WHERE bld_id = ? ORDER BY ord",
                (bld_id,),
            )
        ]
        buildings.append(
            {
                "id": int(bld_id),
                "building": str(building),
                "reserves": int(reserves),
                "ownerships": ownerships,
                "pms": pms,
            }
        )

    pops = [
        {
            "id": int(pop_id),
            "culture": str(culture),
            "religion": str(religion) if religion is not None else None,
            "is_slaves": bool(is_slaves),
            "size": int(size),
        }
        for pop_id, culture, religion, is_slaves, size in conn.execute(
            """
            SELECT id, culture, religion, is_slaves, size
            FROM st_pop
            WHERE tag = ? AND state = ?
            ORDER BY size DESC, culture, IFNULL(religion, ''), is_slaves
            """,
            (tag, state),
        )
    ]

    return {
        "tag": tag,
        "state": state,
        "state_type": str(row[0] or "incorporated"),
        "homelands": homelands,
        "claims": claims,
        "provinces": provinces,
        "hubs": _load_state_hubs(conn, state),
        "buildings": buildings,
        "pops": pops,
    }
