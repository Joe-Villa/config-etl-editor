"""Parse common/history/countries starting technology into a flat table."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from history_states_flat import StateOwnershipRow
from vic3_assign import VIC3_ASSIGN as A, prepare_game_content, read_game_content

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
EXPANSIONS_PATH = PACKAGE_ROOT / "data" / "technology_expansions.json"

COUNTRY_HEADER_RE = re.compile(rf"c:(\w+)\s*{A}\s*\{{")
TIER_EFFECT_RE = re.compile(rf"effect_starting_technology_tier_(\d+)_tech\s*{A}\s*yes")
ERA_RESEARCHED_RE = re.compile(rf"add_era_researched\s*{A}\s*(era_\d+)")
TECH_RESEARCHED_RE = re.compile(rf"add_technology_researched\s*{A}\s*(\w+)")


@dataclass
class CountryTechRow:
    tag: str
    technologies: list[str]

    @property
    def technologies_csv(self) -> str:
        return ",".join(self.technologies)


def _find_block_end(text: str, start: int) -> int:
    from vic3_assign import find_block_end

    return find_block_end(text, start)


def load_technology_expansions(path: Path = EXPANSIONS_PATH) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tiers = {str(key): list(value) for key, value in payload["starting_technology_tiers"].items()}
    eras = {str(key): list(value) for key, value in payload["eras"].items()}
    return tiers, eras


def _append_unique(technologies: list[str], items: list[str]) -> None:
    seen = set(technologies)
    for item in items:
        if item not in seen:
            technologies.append(item)
            seen.add(item)


def _technologies_from_country_block(
    block: str,
    *,
    tier_expansions: dict[str, list[str]],
    era_expansions: dict[str, list[str]],
) -> list[str]:
    events: list[tuple[int, str, str]] = []
    for match in TIER_EFFECT_RE.finditer(block):
        events.append((match.start(), "tier", match.group(1)))
    for match in ERA_RESEARCHED_RE.finditer(block):
        events.append((match.start(), "era", match.group(1)))
    for match in TECH_RESEARCHED_RE.finditer(block):
        events.append((match.start(), "tech", match.group(1)))
    events.sort(key=lambda item: item[0])

    technologies: list[str] = []
    for _, kind, value in events:
        if kind == "tier":
            _append_unique(technologies, tier_expansions.get(value, []))
        elif kind == "era":
            _append_unique(technologies, era_expansions.get(value, []))
        else:
            _append_unique(technologies, [value])
    return technologies


def parse_countries_text(
    text: str,
    *,
    tier_expansions: dict[str, list[str]] | None = None,
    era_expansions: dict[str, list[str]] | None = None,
) -> list[CountryTechRow]:
    if tier_expansions is None or era_expansions is None:
        tier_expansions, era_expansions = load_technology_expansions()

    text = prepare_game_content(text)
    rows: list[CountryTechRow] = []
    for match in COUNTRY_HEADER_RE.finditer(text):
        tag = match.group(1)
        block_start = match.end() - 1
        block_end = _find_block_end(text, block_start)
        block = text[block_start + 1 : block_end]
        technologies = _technologies_from_country_block(
            block,
            tier_expansions=tier_expansions,
            era_expansions=era_expansions,
        )
        rows.append(CountryTechRow(tag=tag, technologies=technologies))
    return rows


def _merge_country_rows(by_tag: dict[str, CountryTechRow], rows: list[CountryTechRow]) -> None:
    for row in rows:
        by_tag[row.tag] = row


def parse_countries_paths(
    paths: list[Path] | tuple[Path, ...],
    *,
    mod_dir: Path | None = None,
    tier_expansions: dict[str, list[str]] | None = None,
    era_expansions: dict[str, list[str]] | None = None,
) -> list[CountryTechRow]:
    from game_content_resolver import is_empty_content_file, split_merged_paths

    if mod_dir is not None:
        vanilla_paths, mod_paths = split_merged_paths(paths, mod_dir)
    else:
        vanilla_paths, mod_paths = list(paths), []

    by_tag: dict[str, CountryTechRow] = {}

    def ingest(path: Path) -> None:
        if is_empty_content_file(path):
            return
        text = read_game_content(path)
        _merge_country_rows(
            by_tag,
            parse_countries_text(
                text,
                tier_expansions=tier_expansions,
                era_expansions=era_expansions,
            ),
        )

    for path in vanilla_paths:
        ingest(path)
    for path in mod_paths:
        ingest(path)

    return list(by_tag.values())


def filter_by_ownership(
    rows: list[CountryTechRow],
    ownership_rows: list[StateOwnershipRow],
) -> list[CountryTechRow]:
    """Keep only tags present in ownership; add empty tech rows for missing tags."""
    active_tags = {row.tag for row in ownership_rows if row.tag}
    by_tag = {row.tag: row for row in rows}
    filtered: list[CountryTechRow] = []
    for tag in sorted(active_tags):
        if tag in by_tag:
            filtered.append(by_tag[tag])
        else:
            filtered.append(CountryTechRow(tag=tag, technologies=[]))
    return filtered


def export_excel(rows: list[CountryTechRow], path: Path) -> Path:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "countries_tech"
    ws.append(["tag", "technologies"])
    for row in rows:
        ws.append([row.tag, row.technologies_csv])
    wb.save(path)
    return path


def rows_to_json(rows: list[CountryTechRow]) -> list[dict[str, Any]]:
    return [{"tag": row.tag, "technologies": row.technologies_csv} for row in rows]
