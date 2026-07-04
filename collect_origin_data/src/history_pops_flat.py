"""Flatten common/history/pops → (state, tag, population) rows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vic3_assign import VIC3_ASSIGN as A, prepare_game_content, read_game_content

STATE_KEY_RE = re.compile(rf"s:(STATE_\w+)\s*{A}\s*\{{")
REGION_KEY_RE = re.compile(rf"region_state:(\w+)\s*{A}\s*\{{")
CREATE_POP_RE = re.compile(rf"create_pop\s*{A}\s*\{{")
SIZE_RE = re.compile(rf"size\s*{A}\s*(-?\d+)")


@dataclass(frozen=True)
class PopByTagRow:
    state: str
    tag: str
    population: int


def _find_block_end(text: str, start: int) -> int:
    from vic3_assign import find_block_end

    return find_block_end(text, start)


def _sum_create_pop_sizes(block: str) -> int:
    total = 0
    for m in CREATE_POP_RE.finditer(block):
        pop_start = m.end() - 1
        pop_end = _find_block_end(block, pop_start)
        inner = block[pop_start + 1 : pop_end]
        size_m = SIZE_RE.search(inner)
        if size_m:
            total += int(size_m.group(1))
    return total


def _parse_state_block(state: str, block: str) -> list[PopByTagRow]:
    rows: list[PopByTagRow] = []
    for m in REGION_KEY_RE.finditer(block):
        tag = m.group(1)
        region_start = m.end() - 1
        region_end = _find_block_end(block, region_start)
        region_block = block[region_start + 1 : region_end]
        population = _sum_create_pop_sizes(region_block)
        rows.append(PopByTagRow(state=state, tag=tag, population=population))
    return rows


def parse_pops_text(text: str) -> list[PopByTagRow]:
    text = prepare_game_content(text)
    rows: list[PopByTagRow] = []
    for m in STATE_KEY_RE.finditer(text):
        state = m.group(1)
        state_start = m.end() - 1
        state_end = _find_block_end(text, state_start)
        state_block = text[state_start + 1 : state_end]
        rows.extend(_parse_state_block(state, state_block))
    return rows


def parse_pops_file(path: Path) -> list[PopByTagRow]:
    return parse_pops_text(read_game_content(path))


def parse_pops_dir(
    pops_dir: Path | None = None,
    *,
    paths: list[Path] | tuple[Path, ...] | None = None,
    mod_dir: Path | None = None,
    skip_example: bool = True,
) -> list[PopByTagRow]:
    if paths is None:
        if pops_dir is None:
            raise ValueError("必须提供 pops_dir 或 paths 参数")
        txt_paths = sorted(pops_dir.glob("*.txt"))
    else:
        txt_paths = list(paths)

    if mod_dir is not None:
        from game_content_resolver import read_merged_paradox_blocks

        text = read_merged_paradox_blocks(
            txt_paths,
            mod_dir,
            r"STATE_\w+",
            line_prefix="s:",
            combine_duplicates=True,
        )
        rows = parse_pops_text(text)
        return sorted(rows, key=lambda r: (r.state, r.tag))

    ingest_paths = txt_paths
    by_key: dict[tuple[str, str], PopByTagRow] = {}
    for path in ingest_paths:
        if skip_example and path.name.startswith("100_"):
            continue
        for row in parse_pops_file(path):
            by_key[(row.state, row.tag)] = row
    rows = sorted(by_key.values(), key=lambda r: (r.state, r.tag))
    return rows


def rows_to_json(rows: list[PopByTagRow]) -> list[dict[str, Any]]:
    return [
        {"state": r.state, "tag": r.tag, "population": r.population}
        for r in rows
    ]


def export_excel(rows: list[PopByTagRow], path: Path) -> Path:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "history_pops"
    ws.append(["state", "tag", "population"])
    for row in rows:
        ws.append([row.state, row.tag, row.population])
    wb.save(path)
    return path


def export_json(rows: list[PopByTagRow], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows_to_json(rows), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
