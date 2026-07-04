"""Flatten map_data/state_regions → one row per state (Excel / JSON)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from vic3_assign import VIC3_ASSIGN as A, block_header, prepare_game_content, read_game_content

STATE_HEADER_RE = re.compile(block_header(r"STATE_\w+"), re.MULTILINE)
SEA_STATE_FILE = "99_seas.txt"
SEA_STATE_ID_MIN = 3000


def is_land_state(row: FlatStateRegion) -> bool:
    return row.id < SEA_STATE_ID_MIN


HUB_TYPES = ("city", "port", "farm", "mine", "wood")


def _norm_province(province: str) -> str:
    text = province.strip()
    if text.lower().startswith("x"):
        return "x" + text[1:].upper()
    return text


class _ImportLog(Protocol):
    def warn(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...


@dataclass(frozen=True)
class ProvinceStateIndex:
    """province → owning state from merged map_data/state_regions."""

    province_to_state: dict[str, str]


def _index_from_rows(
    rows: list[FlatStateRegion],
    log: _ImportLog | None,
    *,
    strict: bool,
    label: str = "map_data/state_regions",
) -> dict[str, str]:
    """Build province→state; strict mode errors on cross-state duplicates."""
    province_to_state: dict[str, str] = {}
    for row in rows:
        seen_in_state: set[str] = set()
        for raw in row.provinces.split(",") if row.provinces else []:
            prov = _norm_province(raw)
            if not prov:
                continue
            if prov in seen_in_state:
                if log is not None:
                    log.warn(
                        f"state_region {row.state} province {prov}：在 provinces 列表中重复"
                    )
                continue
            seen_in_state.add(prov)
            prev_state = province_to_state.get(prov)
            if prev_state is None:
                province_to_state[prov] = row.state
            elif prev_state != row.state:
                if strict and log is not None:
                    log.error(
                        f"map_data 严重错误：province {prov} 同时归属 "
                        f"{prev_state} 与 {row.state}（{label} 中一省只能属一州）"
                    )
                elif not strict:
                    pass
    return province_to_state


def _index_from_paths(
    paths: list[Path] | tuple[Path, ...],
    log: _ImportLog | None,
    *,
    strict: bool,
    label: str,
) -> dict[str, str]:
    if not paths:
        return {}
    rows = parse_state_regions_dir(paths=list(paths), mod_dir=None, land_only=False)
    return _index_from_rows(rows, log, strict=strict, label=label)


def validate_mod_map_data_state_regions(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
    log: _ImportLog,
) -> None:
    """Strict: mod ``map_data/state_regions`` must assign each province to at most one state."""
    from game_content_resolver import resolve_merged_content, split_merged_paths

    merged = resolve_merged_content(
        mod_root, "map_data/state_regions", vanilla, replace_paths=replace_paths
    )
    _, mod_paths = split_merged_paths(list(merged.paths), merged.mod_dir)
    if not mod_paths:
        return
    _index_from_paths(
        mod_paths,
        log,
        strict=True,
        label="mod map_data/state_regions",
    )


def build_authoritative_province_state(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
) -> dict[str, str]:
    """Authoritative province→state: mod-listed provinces use mod; others use vanilla."""
    from game_content_resolver import resolve_merged_content, split_merged_paths

    merged = resolve_merged_content(
        mod_root, "map_data/state_regions", vanilla, replace_paths=replace_paths
    )
    vanilla_paths, mod_paths = split_merged_paths(list(merged.paths), merged.mod_dir)
    if "map_data/state_regions" in replace_paths:
        return _index_from_paths(
            mod_paths,
            None,
            strict=False,
            label="mod map_data/state_regions",
        )
    vanilla_index = _index_from_paths(
        vanilla_paths,
        None,
        strict=False,
        label="vanilla map_data/state_regions",
    )
    mod_index = _index_from_paths(
        mod_paths,
        None,
        strict=False,
        label="mod map_data/state_regions",
    )
    authority = dict(vanilla_index)
    authority.update(mod_index)
    return authority


def states_defined_in_mod_map_data(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
) -> frozenset[str]:
    from game_content_resolver import resolve_merged_content, split_merged_paths

    merged = resolve_merged_content(
        mod_root, "map_data/state_regions", vanilla, replace_paths=replace_paths
    )
    _, mod_paths = split_merged_paths(list(merged.paths), merged.mod_dir)
    if not mod_paths:
        return frozenset()
    rows = parse_state_regions_dir(paths=list(mod_paths), mod_dir=None, land_only=False)
    return frozenset(row.state for row in rows)


def _collect_merged_claims(
    rows: list[FlatStateRegion],
    log: _ImportLog,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    claims: dict[str, list[str]] = {}
    state_provinces: dict[str, list[str]] = {}
    for row in rows:
        seen_in_state: set[str] = set()
        for raw in row.provinces.split(",") if row.provinces else []:
            prov = _norm_province(raw)
            if not prov:
                continue
            if prov in seen_in_state:
                log.warn(
                    f"state_region {row.state} province {prov}：在 provinces 列表中重复"
                )
                continue
            seen_in_state.add(prov)
            state_provinces.setdefault(row.state, []).append(prov)
            claimants = claims.setdefault(prov, [])
            if row.state not in claimants:
                claimants.append(row.state)
    return claims, state_provinces


def _warn_state_should_not_own(
    log: _ImportLog,
    *,
    wrong_state: str,
    prov: str,
    owner_state: str,
) -> None:
    log.warn(
        f"state_region {wrong_state} 不应该拥有 province {prov}"
        f"（map_data 归属 {owner_state}）"
    )


def _pick_fallback_state(
    prov: str,
    candidates: list[str],
    *,
    mod_states: frozenset[str],
    state_tags: dict[str, set[str]],
    state_provinces: dict[str, list[str]],
    resolved: dict[str, str],
) -> str | None:
    if not candidates:
        return None
    scores: dict[str, int] = {}
    for state in candidates:
        score = 0
        if state in mod_states:
            score += 10_000
        score += len(state_tags.get(state, ())) * 100
        siblings = state_provinces.get(state, [])
        score += sum(
            1
            for sibling in siblings
            if sibling != prov and resolved.get(sibling) == state
        )
        scores[state] = score
    best = max(scores.values())
    winners = sorted(state for state, score in scores.items() if score == best)
    return winners[0]


def build_province_state_index(
    rows: list[FlatStateRegion],
    log: _ImportLog,
    *,
    authority: dict[str, str] | None = None,
    mod_states: frozenset[str] | None = None,
    state_tags: dict[str, set[str]] | None = None,
) -> ProvinceStateIndex:
    """Build province ownership from merged state_regions with tolerant cross-state resolution."""
    auth = authority or {}
    mod_state_set = mod_states or frozenset()
    tags = state_tags or {}
    claims, state_provinces = _collect_merged_claims(rows, log)

    province_to_state: dict[str, str] = {}
    for prov in sorted(claims):
        candidates = claims[prov]
        auth_state = auth.get(prov)
        winner: str | None = None

        if auth_state is not None:
            winner = auth_state
            for state in candidates:
                if state != winner:
                    _warn_state_should_not_own(
                        log, wrong_state=state, prov=prov, owner_state=winner
                    )
        elif len(candidates) == 1:
            winner = candidates[0]
        else:
            winner = _pick_fallback_state(
                prov,
                candidates,
                mod_states=mod_state_set,
                state_tags=tags,
                state_provinces=state_provinces,
                resolved=province_to_state,
            )
            if winner is not None:
                for state in candidates:
                    if state != winner:
                        _warn_state_should_not_own(
                            log, wrong_state=state, prov=prov, owner_state=winner
                        )

        if winner is not None:
            province_to_state[prov] = winner

    return ProvinceStateIndex(province_to_state=province_to_state)


@dataclass
class FlatStateRegion:
    id: int
    state: str
    coastal: bool
    provinces: str
    prime_land: str
    impassable: str
    arable_land: int
    arable_resources: str
    city: str = ""
    port: str = ""
    farm: str = ""
    mine: str = ""
    wood: str = ""
    city_name: str = ""
    port_name: str = ""
    farm_name: str = ""
    mine_name: str = ""
    wood_name: str = ""
    resources: dict[str, int] = field(default_factory=dict)


def load_building_list(path: Path) -> list[str]:
    return re.findall(r"building_\w+", path.read_text(encoding="utf-8"))


def _find_block_end(text: str, start: int) -> int:
    from vic3_assign import find_block_end

    return find_block_end(text, start)


def _parse_brace_list(block: str, key: str) -> list[str]:
    m = re.search(rf"{re.escape(key)}\s*{A}\s*\{{", block)
    if not m:
        return []
    start = m.end() - 1
    end = _find_block_end(block, start)
    inner = block[start + 1 : end]
    items: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r'"([^"]+)"', inner):
        if token not in seen:
            seen.add(token)
            items.append(token)
    for token in re.findall(r"\b(x[0-9A-Fa-f]+)\b", inner):
        if token not in seen:
            seen.add(token)
            items.append(token)
    return items


def _parse_int(block: str, key: str, default: int = 0) -> int:
    m = re.search(rf"{re.escape(key)}\s*{A}\s*(-?\d+)", block)
    return int(m.group(1)) if m else default


def _parse_province_ref(block: str, key: str) -> str:
    m = re.search(rf'{re.escape(key)}\s*{A}\s*"([^"]+)"', block)
    if m:
        return m.group(1)
    m = re.search(rf"{re.escape(key)}\s*{A}\s*(x[0-9A-Fa-f]+)", block)
    return m.group(1) if m else ""


def _parse_capped_resources(block: str) -> dict[str, int]:
    m = re.search(rf"capped_resources\s*{A}\s*\{{", block)
    if not m:
        return {}
    start = m.end() - 1
    end = _find_block_end(block, start)
    inner = block[start + 1 : end]
    return {
        name: int(amount)
        for name, amount in re.findall(rf"(building_\w+)\s*{A}\s*(-?\d+)", inner)
    }


def _parse_resource_block_amount(inner: str) -> int:
    """Sum buildable levels from a single `resource = { ... }` block."""
    total = 0
    for m in re.finditer(rf"undiscovered_amount\s*{A}\s*(-?\d+)", inner):
        total += int(m.group(1))
    for m in re.finditer(rf"(?<![\w])discovered_amount\s*{A}\s*(-?\d+)", inner):
        total += int(m.group(1))
    return total


def _parse_resource_blocks(block: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in re.finditer(rf"resource\s*{A}\s*\{{", block):
        start = m.end() - 1
        end = _find_block_end(block, start)
        inner = block[start + 1 : end]
        type_m = re.search(rf'type\s*{A}\s*"([^"]+)"', inner)
        if not type_m:
            continue
        amount = _parse_resource_block_amount(inner)
        if amount == 0:
            continue
        name = type_m.group(1)
        out[name] = out.get(name, 0) + amount
    return out


def _merge_resource_totals(
    resource_blocks: dict[str, int],
    capped: dict[str, int],
) -> dict[str, int]:
    """Merge capped_resources with resource-block types (oil/rubber/gold_field etc.)."""
    merged = dict(resource_blocks)
    for name, amount in capped.items():
        merged[name] = merged.get(name, 0) + amount
    return merged


def parse_state_block(state_name: str, block: str) -> FlatStateRegion:
    provinces = _parse_brace_list(block, "provinces")
    prime_land = _parse_brace_list(block, "prime_land")
    impassable = _parse_brace_list(block, "impassable")
    arable = _parse_brace_list(block, "arable_resources")

    capped = _parse_capped_resources(block)
    resource_blocks = _parse_resource_blocks(block)
    resources = _merge_resource_totals(resource_blocks, capped)

    return FlatStateRegion(
        id=_parse_int(block, "id"),
        state=state_name,
        coastal=bool(_parse_province_ref(block, "port")),
        provinces=",".join(provinces),
        prime_land=",".join(prime_land),
        impassable=",".join(impassable),
        arable_land=_parse_int(block, "arable_land"),
        arable_resources=",".join(arable),
        city=_parse_province_ref(block, "city"),
        port=_parse_province_ref(block, "port"),
        farm=_parse_province_ref(block, "farm"),
        mine=_parse_province_ref(block, "mine"),
        wood=_parse_province_ref(block, "wood"),
        resources=resources,
    )


def _parse_state_regions_text(
    text: str,
    *,
    land_only: bool = True,
) -> list[FlatStateRegion]:
    text = prepare_game_content(text)
    rows: list[FlatStateRegion] = []
    for m in STATE_HEADER_RE.finditer(text):
        state_name = m.group(1)
        block_start = m.end() - 1
        block_end = _find_block_end(text, block_start)
        block = text[block_start + 1 : block_end]
        row = parse_state_block(state_name, block)
        if land_only and not is_land_state(row):
            continue
        rows.append(row)
    return rows


def parse_state_regions_dir(
    regions_dir: Path | None = None,
    *,
    paths: list[Path] | tuple[Path, ...] | None = None,
    mod_dir: Path | None = None,
    resource_columns: list[str] | None = None,
    land_only: bool = True,
) -> list[FlatStateRegion]:
    if paths is None:
        if regions_dir is None:
            raise ValueError("必须提供 regions_dir 或 paths 参数")
        txt_paths = sorted(regions_dir.glob("*.txt"))
    else:
        txt_paths = list(paths)

    if mod_dir is not None:
        from game_content_resolver import read_merged_paradox_blocks

        text = read_merged_paradox_blocks(txt_paths, mod_dir, r"STATE_\w+")
        by_state: dict[str, FlatStateRegion] = {}
        for row in _parse_state_regions_text(text, land_only=land_only):
            by_state[row.state] = row
    else:
        by_state = {}
        for path in txt_paths:
            if land_only and path.name == SEA_STATE_FILE:
                continue
            text = read_game_content(path)
            for row in _parse_state_regions_text(text, land_only=land_only):
                by_state[row.state] = row

    rows = list(by_state.values())
    rows.sort(key=lambda r: (r.id, r.state))
    if resource_columns is not None:
        for row in rows:
            row.resources = {
                col: row.resources.get(col, 0) for col in resource_columns
            }
    return rows


def row_headers(resource_columns: list[str]) -> list[str]:
    return [
        "id",
        "state",
        "coastal",
        "provinces",
        "prime_land",
        "impassable",
        "arable_land",
        "arable_resources",
        *HUB_TYPES,
        *(f"{hub}_name" for hub in HUB_TYPES),
        *resource_columns,
    ]


def row_to_list(row: FlatStateRegion, resource_columns: list[str]) -> list[Any]:
    return [
        row.id,
        row.state,
        row.coastal,
        row.provinces,
        row.prime_land,
        row.impassable,
        row.arable_land,
        row.arable_resources,
        row.city,
        row.port,
        row.farm,
        row.mine,
        row.wood,
        row.city_name,
        row.port_name,
        row.farm_name,
        row.mine_name,
        row.wood_name,
        *(row.resources.get(col, 0) for col in resource_columns),
    ]


def rows_to_json(rows: list[FlatStateRegion], resource_columns: list[str]) -> list[dict[str, Any]]:
    headers = row_headers(resource_columns)
    out: list[dict[str, Any]] = []
    for row in rows:
        values = row_to_list(row, resource_columns)
        out.append(dict(zip(headers, values)))
    return out


def export_excel(
    rows: list[FlatStateRegion],
    path: Path,
    *,
    resource_columns: list[str],
) -> Path:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "state_regions"
    headers = row_headers(resource_columns)
    ws.append(headers)
    for row in rows:
        ws.append(row_to_list(row, resource_columns))
    wb.save(path)
    return path


def export_json(
    rows: list[FlatStateRegion],
    path: Path,
    *,
    resource_columns: list[str],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows_to_json(rows, resource_columns), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path
