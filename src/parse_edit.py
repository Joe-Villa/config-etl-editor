"""Parse editable history/states, history/pops, history/buildings."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from _bootstrap import *  # noqa: F403
from building_flat import (
    _find_block_end,
    _iter_assigned_blocks,
    _ownership_from_building_type,
)
from game_content_resolver import is_empty_content_file, list_txt_files
from history_states_flat import (
    StateMetaRow,
    StateOwnershipRow,
    parse_states_dir,
)
from vic3_assign import VIC3_ASSIGN as A, prepare_game_content, read_game_content

STATE_KEY_RE = re.compile(rf"s:(STATE_\w+)\s*{A}\s*\{{")
REGION_KEY_RE = re.compile(rf"region_state:(\w+)\s*{A}\s*\{{")
CREATE_POP_RE = re.compile(rf"create_pop\s*{A}\s*\{{")
BUILDING_KEY_RE = re.compile(rf'building\s*{A}\s*(?:"([^"]+)"|([\w]+))')


@dataclass(frozen=True)
class PopRow:
    state: str
    tag: str
    culture: str
    religion: str | None
    is_slaves: bool
    size: int


@dataclass(frozen=True)
class OwnershipSlice:
    ownership: str
    level: int
    owner_tag: str = ""
    owner_state: str = ""


@dataclass
class BuildingSite:
    state: str
    tag: str
    building: str
    reserves: int = 1
    pm: list[str] = field(default_factory=list)
    ownerships: list[OwnershipSlice] = field(default_factory=list)


def _extract_country_tag(inner: str) -> str | None:
    m = re.search(rf'country\s*{A}\s*"c:(\w+)"', inner)
    if m:
        return m.group(1)
    m = re.search(rf"country\s*{A}\s*c:(\w+)", inner)
    return m.group(1) if m else None


def _extract_levels(inner: str) -> int | None:
    m = re.search(rf"levels\s*{A}\s*(\d+)", inner)
    return int(m.group(1)) if m else None


def _extract_type(inner: str) -> str | None:
    m = re.search(rf'type\s*{A}\s*"([^"]+)"', inner)
    if m:
        return m.group(1)
    m = re.search(rf"type\s*{A}\s*(\w+)", inner)
    return m.group(1) if m else None


def _extract_region(inner: str) -> str | None:
    m = re.search(rf'region\s*{A}\s*"([^"]+)"', inner)
    if m:
        return m.group(1)
    m = re.search(rf"region\s*{A}\s*(STATE_\w+)", inner)
    return m.group(1) if m else None


def _parse_pm(block: str) -> list[str]:
    m = re.search(rf"activate_production_methods\s*{A}\s*\{{", block)
    if not m:
        return []
    start = m.end() - 1
    end = _find_block_end(block, start)
    inner = block[start + 1 : end]
    tokens = re.findall(r'"([^"]+)"', inner) + re.findall(r"\b(pm_[a-z0-9_]+)\b", inner)
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _parse_pop_block(inner: str) -> PopRow | None:
    culture_m = re.search(rf"culture\s*{A}\s*([a-z][a-z0-9_]*)", inner)
    if not culture_m:
        return None
    size_m = re.search(rf"size\s*{A}\s*(-?\d+)", inner)
    if not size_m:
        return None
    pop_type_m = re.search(rf"pop_type\s*{A}\s*(\w+)", inner)
    religion_m = re.search(rf"religion\s*{A}\s*([a-z][a-z0-9_]*)", inner)
    is_slaves = pop_type_m is not None and pop_type_m.group(1) == "slaves"
    return PopRow(
        state="",
        tag="",
        culture=culture_m.group(1),
        religion=religion_m.group(1) if religion_m else None,
        is_slaves=is_slaves,
        size=int(size_m.group(1)),
    )


def _parse_ownership_slices(
    add_ownership: str, building_name: str, state: str
) -> list[OwnershipSlice]:
    slices: list[OwnershipSlice] = []

    for _key, inner in _iter_assigned_blocks(add_ownership, r"(country)"):
        owner_tag = _extract_country_tag(inner)
        level = _extract_levels(inner)
        if owner_tag is not None and level is not None:
            slices.append(
                OwnershipSlice(
                    ownership="country",
                    level=level,
                    owner_tag=owner_tag,
                    owner_state="",
                )
            )

    for _key, inner in _iter_assigned_blocks(add_ownership, r"(building)"):
        owner_type = _extract_type(inner)
        owner_tag = _extract_country_tag(inner)
        owner_state = _extract_region(inner) or ""
        level = _extract_levels(inner)
        if owner_type and owner_tag is not None and level is not None:
            ownership = _ownership_from_building_type(
                owner_type, building_name, owner_state, state
            )
            slices.append(
                OwnershipSlice(
                    ownership=ownership,
                    level=level,
                    owner_tag=owner_tag,
                    owner_state=owner_state,
                )
            )

    for _key, inner in _iter_assigned_blocks(add_ownership, r"(company)"):
        company_type = _extract_type(inner)
        owner_tag = _extract_country_tag(inner)
        level = _extract_levels(inner)
        if company_type and owner_tag is not None and level is not None:
            slices.append(
                OwnershipSlice(
                    ownership=company_type,
                    level=level,
                    owner_tag=owner_tag,
                    owner_state="",
                )
            )

    return slices


def _parse_create_building_block(block: str, state: str, tag: str) -> BuildingSite | None:
    name_m = BUILDING_KEY_RE.search(block)
    if not name_m:
        return None
    building = name_m.group(1) or name_m.group(2)

    reserves = 1
    reserves_m = re.search(rf"reserves\s*{A}\s*(\d+)", block)
    if reserves_m:
        reserves = int(reserves_m.group(1))

    pm = _parse_pm(block)
    ownerships: list[OwnershipSlice] = []

    ao_m = re.search(rf"add_ownership\s*{A}\s*\{{", block)
    if ao_m:
        ao_start = ao_m.end() - 1
        ao_end = _find_block_end(block, ao_start)
        add_ownership = block[ao_start + 1 : ao_end]
        ownerships = _parse_ownership_slices(add_ownership, building, state)
    else:
        level_m = re.search(rf"level\s*{A}\s*(\d+)", block)
        if level_m:
            ownerships = [
                OwnershipSlice(
                    ownership="country",
                    level=int(level_m.group(1)),
                    owner_tag="",
                    owner_state="",
                )
            ]

    if not ownerships:
        return None

    normalized: list[OwnershipSlice] = []
    for sl in ownerships:
        owner_tag = sl.owner_tag
        owner_state = sl.owner_state
        if not owner_state or owner_state == state:
            owner_state = ""
        if not owner_tag or owner_tag == tag:
            owner_tag = ""
        normalized.append(
            OwnershipSlice(
                ownership=sl.ownership,
                level=sl.level,
                owner_tag=owner_tag,
                owner_state=owner_state,
            )
        )
    ownerships = normalized

    return BuildingSite(
        state=state,
        tag=tag,
        building=building,
        reserves=reserves,
        pm=pm,
        ownerships=ownerships,
    )


def parse_pops_text(text: str) -> list[PopRow]:
    text = prepare_game_content(text)
    rows: list[PopRow] = []
    for m in STATE_KEY_RE.finditer(text):
        state = m.group(1)
        state_start = m.end() - 1
        state_end = _find_block_end(text, state_start)
        state_block = text[state_start + 1 : state_end]
        for rm in REGION_KEY_RE.finditer(state_block):
            tag = rm.group(1)
            region_start = rm.end() - 1
            region_end = _find_block_end(state_block, region_start)
            region_block = state_block[region_start + 1 : region_end]
            for pm in CREATE_POP_RE.finditer(region_block):
                pop_start = pm.end() - 1
                pop_end = _find_block_end(region_block, pop_start)
                inner = region_block[pop_start + 1 : pop_end]
                pop_type_m = re.search(rf"pop_type\s*{A}\s*(\w+)", inner)
                if pop_type_m and pop_type_m.group(1) != "slaves":
                    # 非奴隶 pop_type 不在地图编辑器范围内
                    continue
                parsed = _parse_pop_block(inner)
                if parsed is None:
                    continue
                rows.append(
                    PopRow(
                        state=state,
                        tag=tag,
                        culture=parsed.culture,
                        religion=parsed.religion,
                        is_slaves=parsed.is_slaves,
                        size=parsed.size,
                    )
                )
    return rows


def parse_pops_paths(paths: tuple[Path, ...], *, mod_dir: Path | None = None) -> list[PopRow]:
    if mod_dir is not None:
        from game_content_resolver import read_merged_paradox_blocks

        text = read_merged_paradox_blocks(
            list(paths),
            mod_dir,
            r"STATE_\w+",
            line_prefix="s:",
            combine_duplicates=True,
        )
        texts = [text]
    else:
        texts = []
        for path in paths:
            if path.name.startswith("100_") or is_empty_content_file(path):
                continue
            texts.append(read_game_content(path))

    merged: dict[tuple[str, str, str, str | None, bool], PopRow] = {}
    for text in texts:
        for row in parse_pops_text(text):
            key = (row.state, row.tag, row.culture, row.religion, row.is_slaves)
            if key in merged:
                prev = merged[key]
                merged[key] = PopRow(
                    state=row.state,
                    tag=row.tag,
                    culture=row.culture,
                    religion=row.religion,
                    is_slaves=row.is_slaves,
                    size=prev.size + row.size,
                )
            else:
                merged[key] = row
    return sorted(
        merged.values(),
        key=lambda r: (r.state, r.tag, r.culture, r.religion or "", r.is_slaves),
    )


def parse_buildings_text(text: str) -> list[BuildingSite]:
    text = prepare_game_content(text)
    root_m = re.search(rf"BUILDINGS\s*{A}\s*\{{", text)
    if not root_m:
        return []
    root_start = root_m.end() - 1
    root_end = _find_block_end(text, root_start)
    buildings_inner = text[root_start + 1 : root_end]

    sites: list[BuildingSite] = []
    for state_key, state_inner in _iter_assigned_blocks(buildings_inner, r"(s:(STATE_\w+))"):
        state = state_key.split(":")[1]
        for rs_key, rs_inner in _iter_assigned_blocks(state_inner, r"(region_state:(\w+))"):
            tag = rs_key.split(":")[1]
            pos = 0
            while True:
                cm = re.search(rf"create_building\s*{A}\s*\{{", rs_inner[pos:])
                if not cm:
                    break
                rel = pos + cm.start()
                start = rel + cm.group().index("{")
                end = _find_block_end(rs_inner, start)
                block = rs_inner[start + 1 : end]
                site = _parse_create_building_block(block, state, tag)
                if site is not None:
                    sites.append(site)
                pos = end + 1
    return sites


def parse_buildings_paths(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
) -> list[BuildingSite]:
    if mod_dir is not None:
        from game_content_resolver import merge_paradox_blocks

        blocks = merge_paradox_blocks(
            paths,
            mod_dir,
            r"STATE_\w+",
            line_prefix="s:",
            combine_duplicates=True,
        )
        if not blocks:
            return []
        inner = "\n".join(blocks.values())
        return parse_buildings_text(f"BUILDINGS = {{\n{inner}\n}}")

    sites: list[BuildingSite] = []
    for path in paths:
        if is_empty_content_file(path):
            continue
        sites.extend(
            parse_buildings_text(read_game_content(path))
        )
    return sites


def load_history_states(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
    log: object | None = None,
) -> tuple[list[StateMetaRow], list[StateOwnershipRow]]:
    from content_paths import resolve_game_content

    merged = resolve_game_content(
        mod_root, "common/history/states", vanilla, replace_paths
    )
    return parse_states_dir(
        paths=list(merged.paths),
        mod_dir=merged.mod_dir,
        mod_root=mod_root,
        vanilla=vanilla,
        log=log,
    )


def load_history_pops(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
) -> list[PopRow]:
    from content_paths import resolve_game_content

    merged = resolve_game_content(mod_root, "common/history/pops", vanilla, replace_paths)
    return parse_pops_paths(tuple(merged.paths), mod_dir=merged.mod_dir)


def load_history_buildings(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
) -> list[BuildingSite]:
    from content_paths import resolve_game_content

    merged = resolve_game_content(
        mod_root, "common/history/buildings", vanilla, replace_paths
    )
    return parse_buildings_paths(tuple(merged.paths), mod_dir=merged.mod_dir)
