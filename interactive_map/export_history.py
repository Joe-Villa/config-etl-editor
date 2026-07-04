"""Export editable history data from map_editor.sqlite."""

from __future__ import annotations

import io
import sqlite3
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "map_db"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from _bootstrap import *  # noqa: F403
from building_flat import encode_owner_type  # noqa: E402
from history_states_flat import StateMetaRow, StateOwnershipRow, render_states  # noqa: E402

from history_source_index import FALLBACK_ORD, unique_fallback_name  # noqa: E402
from interactive_map.edit.buildings import (  # noqa: E402
    resolve_owner_state_for_export,
    resolve_owner_tag_for_export,
)

EXPORT_ROOT_NAME = "history"
EXPORT_CATEGORIES = ("buildings", "pops", "states")
EMPTY_ROOT_BLOCKS = {
    "buildings": "BUILDINGS = {\n}\n",
    "pops": "POPS = {\n}\n",
    "states": "STATES = {\n}\n",
}


@dataclass(frozen=True)
class HistorySourceRow:
    state: str
    bld_file: str
    bld_ord: int
    pop_file: str
    pop_ord: int
    st_file: str
    st_ord: int


@dataclass(frozen=True)
class OwnershipExportSlice:
    ownership: str
    level: int
    owner_tag: str
    owner_state: str


@dataclass(frozen=True)
class BuildingExportRow:
    bld_id: int
    state: str
    tag: str
    building: str
    pms: tuple[str, ...]
    ownerships: tuple[OwnershipExportSlice, ...]


@dataclass(frozen=True)
class PopExportRow:
    state: str
    tag: str
    culture: str
    religion: str | None
    is_slaves: bool
    size: int


def load_history_source(conn: sqlite3.Connection) -> dict[str, HistorySourceRow]:
    rows = {
        str(state): HistorySourceRow(
            state=str(state),
            bld_file=str(bld_file),
            bld_ord=int(bld_ord),
            pop_file=str(pop_file),
            pop_ord=int(pop_ord),
            st_file=str(st_file),
            st_ord=int(st_ord),
        )
        for state, bld_file, bld_ord, pop_file, pop_ord, st_file, st_ord in conn.execute(
            """
            SELECT state, bld_file, bld_ord, pop_file, pop_ord, st_file, st_ord
            FROM ref_hist_src
            ORDER BY state
            """
        )
    }
    if not rows:
        raise ValueError("数据库缺少 ref_hist_src，请重新建库")
    return rows


def load_history_files(conn: sqlite3.Connection) -> dict[str, dict[str, bool]]:
    """category -> filename -> is_empty (intentional empty mod override at build time)."""
    index: dict[str, dict[str, bool]] = {category: {} for category in EXPORT_CATEGORIES}
    try:
        rows = conn.execute(
            """
            SELECT category, filename, is_empty
            FROM ref_hist_file
            ORDER BY category, filename
            """
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise ValueError("数据库缺少 ref_hist_file，请重新建库") from exc
    if not rows:
        raise ValueError("数据库缺少 ref_hist_file，请重新建库")
    for category, filename, is_empty in rows:
        index[str(category)][str(filename)] = bool(is_empty)
    return index


def load_buildings_for_export(conn: sqlite3.Connection) -> list[BuildingExportRow]:
    rows: list[BuildingExportRow] = []
    for bld_id, state, tag, building in conn.execute(
        """
        SELECT id, state, tag, building
        FROM st_bld
        ORDER BY state, tag, building, id
        """
    ):
        ownerships: list[OwnershipExportSlice] = []
        for ownership, level, owner_tag, owner_state in conn.execute(
            """
            SELECT ownership, level, owner_tag, owner_state
            FROM st_bld_own
            WHERE bld_id = ?
            ORDER BY ord
            """,
            (bld_id,),
        ):
            ownerships.append(
                OwnershipExportSlice(
                    ownership=str(ownership),
                    level=int(level),
                    owner_tag=resolve_owner_tag_for_export(tag, str(owner_tag)),
                    owner_state=resolve_owner_state_for_export(
                        state, str(owner_state)
                    ),
                )
            )
        pms = tuple(
            str(pm)
            for (pm,) in conn.execute(
                "SELECT pm FROM st_bld_pm WHERE bld_id = ? ORDER BY ord", (bld_id,)
            )
        )
        rows.append(
            BuildingExportRow(
                bld_id=int(bld_id),
                state=str(state),
                tag=str(tag),
                building=str(building),
                pms=pms,
                ownerships=tuple(ownerships),
            )
        )
    return rows


def render_ownership_slice(
    row: BuildingExportRow,
    sl: OwnershipExportSlice,
    *,
    indent: str,
) -> list[str]:
    lines: list[str]
    if sl.ownership == "country":
        lines = [
            f"{indent}country = {{",
            f'{indent}\tcountry = "c:{sl.owner_tag}"',
            f"{indent}\tlevels = {sl.level}",
            f"{indent}}}",
        ]
    elif sl.ownership.startswith("company_"):
        lines = [
            f"{indent}company = {{",
            f"{indent}\ttype = {sl.ownership}",
            f'{indent}\tcountry = "c:{sl.owner_tag}"',
            f"{indent}\tlevels = {sl.level}",
            f"{indent}}}",
        ]
    else:
        owner_type = encode_owner_type(sl.ownership, row.building)
        lines = [
            f"{indent}building = {{",
            f'{indent}\ttype = {owner_type}',
            f'{indent}\tcountry = "c:{sl.owner_tag}"',
            f"{indent}\tlevels = {sl.level}",
            f'{indent}\tregion = "{sl.owner_state}"',
            f"{indent}}}",
        ]
    return lines


def render_create_building(row: BuildingExportRow, *, indent: str = "\t\t\t") -> str:
    lines = [
        f"{indent}create_building = {{",
        f'{indent}\tbuilding = "{row.building}"',
        f"{indent}\tadd_ownership = {{",
    ]
    for sl in row.ownerships:
        lines.extend(render_ownership_slice(row, sl, indent=f"{indent}\t\t"))
    pm_text = " ".join(f'"{pm}"' for pm in row.pms)
    lines.extend(
        [
            f"{indent}\t}}",
            f"{indent}\treserves = 1",
            f"{indent}\tactivate_production_methods = {{ {pm_text}  }}",
            f"{indent}}}",
        ]
    )
    return "\n".join(lines)


def render_history_buildings(
    rows: list[BuildingExportRow],
    *,
    state_order: list[str] | None = None,
    include_empty_states: bool = False,
) -> str:
    allowed = set(state_order) if state_order is not None else None
    state_order_list = list(state_order or ())
    tag_order: dict[str, list[str]] = {}
    groups: dict[str, dict[str, list[BuildingExportRow]]] = {}

    for row in rows:
        if allowed is not None and row.state not in allowed:
            continue
        if row.state not in groups:
            groups[row.state] = {}
            if state_order is None:
                state_order_list.append(row.state)
            tag_order[row.state] = []
        if row.tag not in groups[row.state]:
            groups[row.state][row.tag] = []
            tag_order[row.state].append(row.tag)
        groups[row.state][row.tag].append(row)

    if state_order is not None:
        if include_empty_states:
            state_order_list = list(state_order)
        else:
            state_order_list = [state for state in state_order if state in groups]

    lines = ["BUILDINGS = {"]
    for state in state_order_list:
        lines.append(f"\ts:{state} = {{")
        if state in groups:
            for tag in tag_order[state]:
                lines.append(f"\t\tregion_state:{tag} = {{")
                for row in groups[state][tag]:
                    lines.append(render_create_building(row, indent="\t\t\t"))
                lines.append("\t\t}")
        lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def load_states_for_export(
    conn: sqlite3.Connection,
) -> tuple[list[StateMetaRow], list[StateOwnershipRow]]:
    meta_rows: list[StateMetaRow] = []
    for (state,) in conn.execute("SELECT state FROM geo_state ORDER BY state"):
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
        meta_rows.append(
            StateMetaRow(state=str(state), homelands=homelands, claims=claims)
        )

    ownership_rows: list[StateOwnershipRow] = []
    for state, tag, state_type in conn.execute(
        "SELECT state, tag, state_type FROM st ORDER BY state, tag"
    ):
        provinces = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT province FROM st_prov
                WHERE state = ? AND tag = ?
                ORDER BY province
                """,
                (state, tag),
            )
        ]
        ownership_rows.append(
            StateOwnershipRow(
                state=str(state),
                tag=str(tag),
                owned_provinces=provinces,
                state_type=str(state_type or "incorporated"),
            )
        )
    return meta_rows, ownership_rows


def render_history_states(
    conn: sqlite3.Connection,
    *,
    state_order: list[str] | None = None,
    include_empty_states: bool = False,
) -> str:
    meta_rows, ownership_rows = load_states_for_export(conn)
    if state_order is None:
        return render_states(meta_rows, ownership_rows)

    meta_by = {row.state: row for row in meta_rows}
    own_by: dict[str, list[StateOwnershipRow]] = defaultdict(list)
    for row in ownership_rows:
        own_by[row.state].append(row)

    lines = ["STATES = {"]
    for state in state_order:
        if not include_empty_states and state not in meta_by and state not in own_by:
            continue
        lines.append(f"\ts:{state} = {{")
        for own in own_by.get(state, []):
            lines.append("\t\tcreate_state = {")
            lines.append(f"\t\t\tcountry = c:{own.tag}")
            if own.state_type == "unincorporated":
                lines.append("\t\t\tstate_type = unincorporated")
            provinces = " ".join(own.owned_provinces)
            lines.append(f"\t\t\towned_provinces = {{ {provinces} }}")
            lines.append("\t\t}")
            lines.append("")
        meta = meta_by.get(state, StateMetaRow(state=state))
        for homeland in meta.homelands:
            lines.append(f"\t\tadd_homeland = cu:{homeland}")
        for claim in meta.claims:
            lines.append(f"\t\tadd_claim = c:{claim}")
        lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def load_pops_for_export(conn: sqlite3.Connection) -> list[PopExportRow]:
    rows: list[PopExportRow] = []
    for state, tag, culture, religion, is_slaves, size in conn.execute(
        """
        SELECT state, tag, culture, religion, is_slaves, size
        FROM st_pop
        ORDER BY state, tag, culture, IFNULL(religion, ''), is_slaves, size DESC
        """
    ):
        rows.append(
            PopExportRow(
                state=str(state),
                tag=str(tag),
                culture=str(culture),
                religion=str(religion) if religion is not None else None,
                is_slaves=bool(is_slaves),
                size=int(size),
            )
        )
    return rows


def render_create_pop(row: PopExportRow, *, indent: str = "\t\t\t") -> str:
    lines = [
        f"{indent}create_pop = {{",
        f"{indent}\tculture = {row.culture}",
    ]
    if row.religion:
        lines.append(f"{indent}\treligion = {row.religion}")
    if row.is_slaves:
        lines.append(f"{indent}\tpop_type = slaves")
    lines.extend(
        [
            f"{indent}\tsize = {row.size}",
            f"{indent}}}",
        ]
    )
    return "\n".join(lines)


def render_history_pops(
    rows: list[PopExportRow],
    *,
    state_order: list[str] | None = None,
    include_empty_states: bool = False,
) -> str:
    allowed = set(state_order) if state_order is not None else None
    state_order_list = list(state_order or ())
    tag_order: dict[str, list[str]] = {}
    groups: dict[str, dict[str, list[PopExportRow]]] = {}

    for row in rows:
        if allowed is not None and row.state not in allowed:
            continue
        if row.state not in groups:
            groups[row.state] = {}
            if state_order is None:
                state_order_list.append(row.state)
            tag_order[row.state] = []
        if row.tag not in groups[row.state]:
            groups[row.state][row.tag] = []
            tag_order[row.state].append(row.tag)
        groups[row.state][row.tag].append(row)

    if state_order is not None:
        if include_empty_states:
            state_order_list = list(state_order)
        else:
            state_order_list = [state for state in state_order if state in groups]

    lines = ["POPS = {"]
    for state in state_order_list:
        lines.append(f"\ts:{state} = {{")
        if state in groups:
            for tag in tag_order[state]:
                lines.append(f"\t\tregion_state:{tag} = {{")
                for row in groups[state][tag]:
                    lines.append(render_create_pop(row, indent="\t\t\t"))
                lines.append("\t\t}")
        lines.append("\t}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _ensure_lazy_fallback(
    category: str,
    file_index: dict[str, dict[str, bool]],
    lazy_fallback: dict[str, str],
) -> str:
    if category not in lazy_fallback:
        lazy_fallback[category] = unique_fallback_name(set(file_index[category].keys()))
        file_index[category][lazy_fallback[category]] = False
    return lazy_fallback[category]


def _resolve_fallback_name(
    category: str,
    file_index: dict[str, dict[str, bool]],
    lazy_fallback: dict[str, str],
) -> str:
    if category in lazy_fallback:
        return lazy_fallback[category]
    for filename in sorted(file_index[category]):
        if filename.startswith("_fallback"):
            return filename
    return ""


def _group_states_by_export_file(
    source: dict[str, HistorySourceRow],
    *,
    file_attr: str,
    ord_attr: str,
    states_with_data: set[str],
    category: str,
    file_index: dict[str, dict[str, bool]],
    lazy_fallback: dict[str, str],
) -> tuple[dict[str, list[str]], str]:
    """Group states per output file; fallback lists all assigned states (even without data)."""
    fallback = _resolve_fallback_name(category, file_index, lazy_fallback)
    by_file: dict[str, list[tuple[int, str]]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)

    if fallback:
        for state, row in source.items():
            if getattr(row, file_attr) != fallback:
                continue
            if state in seen[fallback]:
                continue
            seen[fallback].add(state)
            by_file[fallback].append((getattr(row, ord_attr), state))

    for state in states_with_data:
        row = source[state]
        filename = getattr(row, file_attr)
        if not filename:
            filename = _ensure_lazy_fallback(category, file_index, lazy_fallback)
            ord_ = FALLBACK_ORD
        else:
            ord_ = getattr(row, ord_attr)
        if state in seen[filename]:
            continue
        seen[filename].add(state)
        by_file[filename].append((ord_, state))

    grouped = {
        filename: [state for _, state in sorted(items)]
        for filename, items in by_file.items()
    }
    return grouped, fallback


def export_history_files(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Return {category: {filename: content}} following ref_hist_src layout."""
    source = load_history_source(conn)
    file_index = load_history_files(conn)
    building_rows = load_buildings_for_export(conn)
    pop_rows = load_pops_for_export(conn)
    geo_states = {
        str(row[0])
        for row in conn.execute("SELECT state FROM geo_state ORDER BY state")
    }

    bld_states = {row.state for row in building_rows}
    pop_states = {row.state for row in pop_rows}
    lazy_fallback: dict[str, str] = {}

    bld_by_state, fb_bld = _group_states_by_export_file(
        source,
        file_attr="bld_file",
        ord_attr="bld_ord",
        states_with_data=bld_states,
        category="buildings",
        file_index=file_index,
        lazy_fallback=lazy_fallback,
    )
    pop_by_state, fb_pop = _group_states_by_export_file(
        source,
        file_attr="pop_file",
        ord_attr="pop_ord",
        states_with_data=pop_states,
        category="pops",
        file_index=file_index,
        lazy_fallback=lazy_fallback,
    )
    st_by_state, fb_st = _group_states_by_export_file(
        source,
        file_attr="st_file",
        ord_attr="st_ord",
        states_with_data=geo_states,
        category="states",
        file_index=file_index,
        lazy_fallback=lazy_fallback,
    )

    bld_content = {
        filename: render_history_buildings(
            building_rows,
            state_order=state_order,
            include_empty_states=bool(fb_bld and filename == fb_bld),
        )
        for filename, state_order in bld_by_state.items()
    }
    pop_content = {
        filename: render_history_pops(
            pop_rows,
            state_order=state_order,
            include_empty_states=bool(fb_pop and filename == fb_pop),
        )
        for filename, state_order in pop_by_state.items()
    }
    st_content = {
        filename: render_history_states(
            conn,
            state_order=state_order,
            include_empty_states=bool(fb_st and filename == fb_st),
        )
        for filename, state_order in st_by_state.items()
    }

    return {
        "buildings": _merge_history_file_contents("buildings", file_index, bld_content),
        "pops": _merge_history_file_contents("pops", file_index, pop_content),
        "states": _merge_history_file_contents("states", file_index, st_content),
    }


def _merge_history_file_contents(
    category: str,
    file_index: dict[str, dict[str, bool]],
    rendered: dict[str, str],
) -> dict[str, str]:
    out: dict[str, str] = {}
    for filename in sorted(file_index[category].keys()):
        if file_index[category][filename]:
            out[filename] = ""
        elif filename in rendered:
            out[filename] = rendered[filename]
        else:
            out[filename] = EMPTY_ROOT_BLOCKS[category]
    for filename, content in rendered.items():
        if filename not in out:
            out[filename] = content
    return out


def export_history_bundle(conn: sqlite3.Connection) -> dict[str, str]:
    """Legacy flat export: merge all files in each category into one text blob."""
    files = export_history_files(conn)
    return {
        category: "".join(
            content for _, content in sorted(file_map.items())
        )
        for category, file_map in files.items()
    }


def export_history_zip(conn: sqlite3.Connection, *, root_name: str = EXPORT_ROOT_NAME) -> bytes:
    files = export_history_files(conn)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for category in EXPORT_CATEGORIES:
            for filename, content in sorted(files.get(category, {}).items()):
                archive.writestr(f"{root_name}/{category}/{filename}", content)
    return buffer.getvalue()
