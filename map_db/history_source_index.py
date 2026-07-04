"""Index which history file each state belongs to (static at database build).

File resolution matches game content merge rules:
- Same relative path + same filename: only the mod file is used; vanilla is not read.
- Different filenames: both may contribute; scan vanilla files first, then mod files,
  so mod wins when the same state appears in both.
- Intentionally empty mod files (to override vanilla) are recorded in ref_hist_file.
- _fallback.txt is created lazily per category: only when imported data references a
  state that does not appear in any history file for that category. Export fills it
  with those state blocks (empty blocks when a state has no rows in that category).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from _bootstrap import *  # noqa: F403
from content_paths import resolve_game_content
from game_content_resolver import (
    is_empty_content_file,
    path_is_from_mod,
)
from vic3_assign import VIC3_ASSIGN as A, prepare_game_content, read_game_content

STATE_KEY_RE = re.compile(rf"s:(STATE_\w+)\s*{A}\s*\{{")
FALLBACK_BASE = "_fallback.txt"
FALLBACK_ORD = 1_000_000
NO_FILE = ""

HISTORY_CATEGORIES = ("buildings", "pops", "states")
HISTORY_DIRS: dict[str, tuple[str, str | None]] = {
    "buildings": ("common/history/buildings", None),
    "pops": ("common/history/pops", "100_"),
    "states": ("common/history/states", None),
}


@dataclass(frozen=True)
class HistorySourceSlot:
    file: str
    ord: int


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
class HistoryFileRow:
    category: str
    filename: str
    is_empty: bool


def unique_fallback_name(existing: set[str], base: str = FALLBACK_BASE) -> str:
    name = base
    while name in existing:
        name = name[:-4] + "a" + name[-4:]
    return name


def scan_state_keys_in_text(text: str) -> list[str]:
    text = prepare_game_content(text)
    return [match.group(1) for match in STATE_KEY_RE.finditer(text)]


def _effective_history_paths(
    mod_root: Path,
    vanilla: Path,
    relative: str,
    replace_paths: frozenset[str],
) -> tuple[Path, ...]:
    """Paths to scan: one entry per filename (mod replaces vanilla), vanilla group first."""
    merged = resolve_game_content(mod_root, relative, vanilla, replace_paths)
    vanilla_paths: list[Path] = []
    mod_paths: list[Path] = []
    for path in merged.paths:
        if merged.mod_dir is not None and path_is_from_mod(path, merged.mod_dir):
            mod_paths.append(path)
        else:
            vanilla_paths.append(path)
    vanilla_paths.sort(key=lambda item: item.name)
    mod_paths.sort(key=lambda item: item.name)
    return tuple(vanilla_paths + mod_paths)


def _category_paths(
    mod_root: Path,
    vanilla: Path,
    category: str,
    replace_paths: frozenset[str],
) -> tuple[Path, ...]:
    relative, skip_prefix = HISTORY_DIRS[category]
    paths: list[Path] = []
    for path in _effective_history_paths(mod_root, vanilla, relative, replace_paths):
        if skip_prefix and path.name.startswith(skip_prefix):
            continue
        paths.append(path)
    return tuple(paths)


def _ingest_paths(
    mod_root: Path,
    vanilla: Path,
    category: str,
    replace_paths: frozenset[str],
) -> tuple[Path, ...]:
    return tuple(
        path
        for path in _category_paths(mod_root, vanilla, category, replace_paths)
        if not is_empty_content_file(path)
    )


def scan_history_state_sources(paths: tuple[Path, ...]) -> dict[str, HistorySourceSlot]:
    mapping: dict[str, HistorySourceSlot] = {}
    for path in paths:
        for ord_, state in enumerate(
            scan_state_keys_in_text(
                read_game_content(path)
            ),
            start=1,
        ):
            mapping[state] = HistorySourceSlot(path.name, ord_)
    return mapping


def _states_with_imported_data(
    conn: sqlite3.Connection, category: str
) -> set[str]:
    if category == "buildings":
        return {
            str(row[0])
            for row in conn.execute("SELECT DISTINCT state FROM st_bld")
        }
    if category == "pops":
        return {
            str(row[0])
            for row in conn.execute("SELECT DISTINCT state FROM st_pop")
        }
    return {str(row[0]) for row in conn.execute("SELECT state FROM geo_state")}


def _slot_for_state(
    state: str,
    mapping: dict[str, HistorySourceSlot],
    needs_fallback: set[str],
    fallback_name: str,
) -> HistorySourceSlot:
    if state in mapping:
        return mapping[state]
    if state in needs_fallback:
        return HistorySourceSlot(fallback_name, FALLBACK_ORD)
    return HistorySourceSlot(NO_FILE, 0)


def build_history_file_rows(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
    *,
    fallback_names: dict[str, str] | None = None,
) -> list[HistoryFileRow]:
    rows: list[HistoryFileRow] = []
    seen: dict[str, set[str]] = {category: set() for category in HISTORY_CATEGORIES}
    for category in HISTORY_CATEGORIES:
        for path in _category_paths(mod_root, vanilla, category, replace_paths):
            if path.name in seen[category]:
                continue
            seen[category].add(path.name)
            rows.append(
                HistoryFileRow(
                    category=category,
                    filename=path.name,
                    is_empty=is_empty_content_file(path),
                )
            )
        if fallback_names and category in fallback_names:
            fb = fallback_names[category]
            if fb not in seen[category]:
                rows.append(HistoryFileRow(category=category, filename=fb, is_empty=False))
    return rows


def build_history_source_rows(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
    all_states: list[str],
    conn: sqlite3.Connection,
) -> tuple[list[HistoryFileRow], list[HistorySourceRow]]:
    bld_paths = _ingest_paths(mod_root, vanilla, "buildings", replace_paths)
    pop_paths = _ingest_paths(mod_root, vanilla, "pops", replace_paths)
    st_paths = _ingest_paths(mod_root, vanilla, "states", replace_paths)

    bld_map = scan_history_state_sources(bld_paths)
    pop_map = scan_history_state_sources(pop_paths)
    st_map = scan_history_state_sources(st_paths)

    bld_files = {
        path.name for path in _category_paths(mod_root, vanilla, "buildings", replace_paths)
    }
    pop_files = {
        path.name for path in _category_paths(mod_root, vanilla, "pops", replace_paths)
    }
    st_files = {
        path.name for path in _category_paths(mod_root, vanilla, "states", replace_paths)
    }

    bld_needs = _states_with_imported_data(conn, "buildings") - set(bld_map.keys())
    pop_needs = _states_with_imported_data(conn, "pops") - set(pop_map.keys())
    st_needs = _states_with_imported_data(conn, "states") - set(st_map.keys())

    fallbacks: dict[str, str] = {}
    if bld_needs:
        fallbacks["buildings"] = unique_fallback_name(bld_files)
    if pop_needs:
        fallbacks["pops"] = unique_fallback_name(pop_files)
    if st_needs:
        fallbacks["states"] = unique_fallback_name(st_files)

    fb_bld = fallbacks.get("buildings", NO_FILE)
    fb_pop = fallbacks.get("pops", NO_FILE)
    fb_st = fallbacks.get("states", NO_FILE)

    source_rows: list[HistorySourceRow] = []
    for state in all_states:
        bld = _slot_for_state(state, bld_map, bld_needs, fb_bld)
        pop = _slot_for_state(state, pop_map, pop_needs, fb_pop)
        st = _slot_for_state(state, st_map, st_needs, fb_st)
        source_rows.append(
            HistorySourceRow(
                state=state,
                bld_file=bld.file,
                bld_ord=bld.ord,
                pop_file=pop.file,
                pop_ord=pop.ord,
                st_file=st.file,
                st_ord=st.ord,
            )
        )

    file_rows = build_history_file_rows(
        mod_root, vanilla, replace_paths, fallback_names=fallbacks or None
    )
    return file_rows, source_rows


def insert_history_file_rows(
    conn: sqlite3.Connection, rows: list[HistoryFileRow]
) -> None:
    conn.executemany(
        """
        INSERT INTO ref_hist_file (category, filename, is_empty)
        VALUES (?, ?, ?)
        """,
        [(row.category, row.filename, int(row.is_empty)) for row in rows],
    )


def insert_history_source_rows(
    conn: sqlite3.Connection, rows: list[HistorySourceRow]
) -> None:
    conn.executemany(
        """
        INSERT INTO ref_hist_src (
            state, bld_file, bld_ord, pop_file, pop_ord, st_file, st_ord
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row.state,
                row.bld_file,
                row.bld_ord,
                row.pop_file,
                row.pop_ord,
                row.st_file,
                row.st_ord,
            )
            for row in rows
        ],
    )


def insert_history_index(
    conn: sqlite3.Connection,
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
    all_states: list[str],
) -> None:
    file_rows, source_rows = build_history_source_rows(
        mod_root, vanilla, replace_paths, all_states, conn
    )
    insert_history_file_rows(conn, file_rows)
    insert_history_source_rows(conn, source_rows)
