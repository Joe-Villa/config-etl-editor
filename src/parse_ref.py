"""Parse reference catalog files for map editor."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from _bootstrap import *  # noqa: F403
from vic3_assign import (
    VIC3_ASSIGN as A,
    block_header,
    iter_top_level_block_matches,
    prepare_game_content,
    read_game_content,
)

from content_paths import (
    merged_content,
    merged_history_buildings_text,
    merged_paradox_text,
    resolve_game_content,
)
from country_definitions_flat import (
    _find_block_end,
    _parse_color,
    COUNTRY_HEADER_RE,
    COUNTRY_DEFINITION_TAG_ID,
    parse_country_definitions_paths,
    resolve_country_definition_map_color,
    scan_country_definitions_paths_errors,
)
from game_content_resolver import is_empty_content_file, ordered_merge_paths, read_txt_paths
from state_region_flat import FlatStateRegion, parse_state_regions_dir


@dataclass(frozen=True)
class TagRow:
    tag: str
    r: int
    g: int
    b: int
    capital_state: str = ""
    country_type: str = ""
    cultures: tuple[str, ...] = ()


@dataclass(frozen=True)
class CultureRow:
    culture: str
    default_religion: str
    r: int
    g: int
    b: int


@dataclass(frozen=True)
class ReligionRow:
    religion: str
    r: int
    g: int
    b: int


@dataclass(frozen=True)
class BuildingGroupRow:
    building_group: str
    parent_group: str | None = None


@dataclass(frozen=True)
class BuildingRow:
    building: str
    building_group: str
    pm_groups: tuple[str, ...]
    buildable: bool = True


@dataclass(frozen=True)
class PmGroupRow:
    pm_group: str
    pms: tuple[str, ...]


@dataclass(frozen=True)
class StrategicRegionRow:
    region: str
    capital_province: str
    map_r: float
    map_g: float
    map_b: float
    states: tuple[str, ...]


@dataclass(frozen=True)
class LocRow:
    key: str
    text: str


RELIGION_NESTED_BLOCK_IDS = frozenset({"color", "taboos"})
RELIGION_TRAITS_RE = re.compile(rf"\btraits\s*{A}\s*\{{", re.MULTILINE)


def parse_religions_text(
    text: str,
    *,
    warnings: list[str] | None = None,
) -> list[ReligionRow]:
    rows: list[ReligionRow] = []
    for match in iter_top_level_block_matches(text, r"[a-z][a-z0-9_]*"):
        religion = match.group(1)
        if religion in RELIGION_NESTED_BLOCK_IDS:
            continue
        start = match.end() - 1
        end = _find_block_end(text, start)
        block = text[start + 1 : end]
        if religion == "traits" or RELIGION_TRAITS_RE.search(block):
            if warnings is not None:
                warnings.append(f"宗教 {religion}：过时的宗教写法")
            if religion == "traits":
                continue
        rgb = _parse_color(block)
        if rgb is None:
            r, g, b = 255, 255, 255
        else:
            r, g, b = rgb
        rows.append(ReligionRow(religion=religion, r=r, g=g, b=b))
    return sorted(rows, key=lambda row: row.religion)


def _merged_block_text(
    paths: tuple[Path, ...],
    mod_dir: Path | None,
    id_pattern: str,
    *,
    line_prefix: str = "",
) -> str:
    if mod_dir is not None:
        from game_content_resolver import read_merged_paradox_blocks

        return read_merged_paradox_blocks(
            paths,
            mod_dir,
            id_pattern,
            line_prefix=line_prefix,
        )
    return read_txt_paths(paths)


def parse_religions_paths(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
    *,
    warnings: list[str] | None = None,
) -> list[ReligionRow]:
    text = _merged_block_text(paths, mod_dir, r"[a-z][a-z0-9_]*")
    return parse_religions_text(text, warnings=warnings)


def parse_cultures_text(text: str) -> list[CultureRow]:
    rows: list[CultureRow] = []
    for match in re.finditer(
        block_header(r"[a-z][a-z0-9_]*"), text, flags=re.MULTILINE
    ):
        culture = match.group(1)
        start = match.end() - 1
        end = _find_block_end(text, start)
        block = text[start + 1 : end]
        rel_m = re.search(rf"religion\s*{A}\s*([a-z][a-z0-9_]*)", block)
        if not rel_m:
            continue
        rgb = _parse_color(block)
        if rgb is None:
            r, g, b = 255, 255, 255
        else:
            r, g, b = rgb
        rows.append(
            CultureRow(
                culture=culture,
                default_religion=rel_m.group(1),
                r=r,
                g=g,
                b=b,
            )
        )
    return rows


def parse_cultures_paths(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
) -> list[CultureRow]:
    text = _merged_block_text(paths, mod_dir, r"[a-z][a-z0-9_]*")
    return parse_cultures_text(text)


def parse_building_groups_text(text: str) -> list[BuildingGroupRow]:
    rows: list[BuildingGroupRow] = []
    for match in re.finditer(
        block_header(r"bg_[a-z0-9_]+"), text, flags=re.MULTILINE
    ):
        building_group = match.group(1)
        start = match.end() - 1
        end = _find_block_end(text, start)
        block = text[start + 1 : end]
        parent_m = re.search(rf"parent_group\s*{A}\s*(bg_[a-z0-9_]*)", block)
        parent_group = parent_m.group(1) if parent_m else None
        rows.append(
            BuildingGroupRow(
                building_group=building_group,
                parent_group=parent_group,
            )
        )
    return rows


def parse_building_groups_paths(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
) -> list[BuildingGroupRow]:
    text = _merged_block_text(paths, mod_dir, r"bg_[a-z0-9_]+")
    return parse_building_groups_text(text)


def resolve_root_group(
    building_group: str, parent_map: dict[str, str | None]
) -> str:
    seen: set[str] = set()
    current = building_group
    while True:
        parent = parent_map.get(current)
        if not parent or parent in seen:
            return current
        seen.add(current)
        current = parent


def resolve_root_groups(rows: list[BuildingGroupRow]) -> dict[str, str]:
    parent_map = {row.building_group: row.parent_group for row in rows}
    return {
        row.building_group: resolve_root_group(row.building_group, parent_map)
        for row in rows
    }


def _parse_brace_keys(block: str, key: str) -> list[str]:
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
    for token in re.findall(r"\b(STATE_[A-Z0-9_]+)\b", inner):
        if token not in seen:
            seen.add(token)
            items.append(token)
    for token in re.findall(r"\b([a-z][a-z0-9_]*)\b", inner):
        if token not in seen:
            seen.add(token)
            items.append(token)
    return items


def parse_buildings_text(text: str) -> list[BuildingRow]:
    rows: list[BuildingRow] = []
    for match in re.finditer(
        block_header(r"building_[a-z0-9_]+"), text, flags=re.MULTILINE
    ):
        building = match.group(1)
        start = match.end() - 1
        end = _find_block_end(text, start)
        block = text[start + 1 : end]
        bg_m = re.search(rf"building_group\s*{A}\s*(bg_[a-z0-9_]*)", block)
        if not bg_m:
            continue
        buildable_m = re.search(rf"buildable\s*{A}\s*(yes|no)", block)
        buildable = buildable_m.group(1) != "no" if buildable_m else True
        pm_groups = tuple(_parse_brace_keys(block, "production_method_groups"))
        rows.append(
            BuildingRow(
                building=building,
                building_group=bg_m.group(1),
                pm_groups=pm_groups,
                buildable=buildable,
            )
        )
    return rows


def parse_buildings_paths(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
) -> list[BuildingRow]:
    text = _merged_block_text(paths, mod_dir, r"building_[a-z0-9_]+")
    return parse_buildings_text(text)


def parse_pm_groups_text(text: str) -> list[PmGroupRow]:
    rows: list[PmGroupRow] = []
    for match in re.finditer(
        block_header(r"pmg_[a-z0-9_]+"), text, flags=re.MULTILINE
    ):
        pm_group = match.group(1)
        start = match.end() - 1
        end = _find_block_end(text, start)
        block = text[start + 1 : end]
        pms = tuple(_parse_brace_keys(block, "production_methods"))
        rows.append(PmGroupRow(pm_group=pm_group, pms=pms))
    return rows


def parse_pm_groups_paths(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
) -> list[PmGroupRow]:
    text = _merged_block_text(paths, mod_dir, r"pmg_[a-z0-9_]+")
    return parse_pm_groups_text(text)


def parse_company_types_text(text: str) -> list[str]:
    return sorted(
        {
            m.group(1)
            for m in re.finditer(
                block_header(r"company_[a-z0-9_]+"), text, flags=re.MULTILINE
            )
        }
    )


def parse_company_types_paths(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
) -> list[str]:
    text = _merged_block_text(paths, mod_dir, r"company_[a-z0-9_]+")
    return parse_company_types_text(text)


def parse_country_definitions_extended(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
    *,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> list[TagRow]:
    if mod_dir is not None:
        text = _merged_block_text(
            paths,
            mod_dir,
            COUNTRY_DEFINITION_TAG_ID,
        )
        path_iter: list[str] = [text]
    else:
        path_iter = []
        for path in paths:
            if is_empty_content_file(path):
                continue
            path_iter.append(read_game_content(path))

    rows: list[TagRow] = []
    for text in path_iter:
        for match in COUNTRY_HEADER_RE.finditer(text):
            tag = match.group(1)
            block_start = match.end() - 1
            block_end = _find_block_end(text, block_start)
            block = text[block_start + 1 : block_end]
            rgb, _fallback_reason = resolve_country_definition_map_color(
                block,
                named_colors=named_colors,
            )
            if rgb is None:
                continue
            cap_m = re.search(rf"capital\s*{A}\s*(STATE_[A-Z0-9_]+)", block)
            type_m = re.search(rf"country_type\s*{A}\s*(\w+)", block)
            cultures = tuple(_parse_brace_keys(block, "cultures"))
            r, g, b = rgb
            rows.append(
                TagRow(
                    tag=tag,
                    r=r,
                    g=g,
                    b=b,
                    capital_state=cap_m.group(1) if cap_m else "",
                    country_type=type_m.group(1) if type_m else "recognized",
                    cultures=cultures,
                )
            )
    return rows


def merge_tag_rows(
    vanilla_paths: tuple[Path, ...],
    mod_paths: tuple[Path, ...],
    mod_dir: Path | None = None,
    *,
    mod_root: Path | None = None,
    vanilla: Path | None = None,
    log: object | None = None,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> list[TagRow]:
    if mod_dir is not None:
        all_paths = tuple(vanilla_paths) + tuple(mod_paths)
        if log is not None and mod_root is not None and vanilla is not None:
            scan_country_definitions_paths_errors(
                all_paths,
                mod_dir,
                mod_root,
                vanilla,
                log,
                named_colors=named_colors,
            )
        return sorted(
            parse_country_definitions_extended(
                all_paths,
                mod_dir=mod_dir,
                named_colors=named_colors,
            ),
            key=lambda r: r.tag,
        )
    by_tag: dict[str, TagRow] = {}
    for row in parse_country_definitions_extended(
        vanilla_paths, named_colors=named_colors
    ):
        by_tag[row.tag] = row
    for row in parse_country_definitions_extended(
        mod_paths, named_colors=named_colors
    ):
        by_tag[row.tag] = row
    return sorted(by_tag.values(), key=lambda r: r.tag)


def parse_strategic_regions_text(text: str) -> list[StrategicRegionRow]:
    rows: list[StrategicRegionRow] = []
    for match in re.finditer(
        block_header(r"region_[a-z0-9_]+"), text, flags=re.MULTILINE
    ):
        region = match.group(1)
        start = match.end() - 1
        end = _find_block_end(text, start)
        block = text[start + 1 : end]
        cap_m = re.search(rf"capital_province\s*{A}\s*(x[0-9A-Fa-f]+)", block)
        map_color = _parse_map_color_rgb(block)
        if map_color is None:
            continue
        map_r, map_g, map_b = map_color
        states = tuple(
            token
            for token in re.findall(r"\b(STATE_[A-Z0-9_]+)\b", block)
            if token != (cap_m.group(1) if cap_m else None)
        )
        # states list is inside `states = { ... }` — re-parse from that block only
        states = tuple(_parse_brace_keys(block, "states"))
        rows.append(
            StrategicRegionRow(
                region=region,
                capital_province=cap_m.group(1) if cap_m else "",
                map_r=map_r,
                map_g=map_g,
                map_b=map_b,
                states=states,
            )
        )
    return rows


_MAP_COLOR_BLOCK_RE = re.compile(
    rf"map_color\s*{A}\s*\{{([^}}]*)}}",
    flags=re.DOTALL,
)


def _parse_map_color_rgb(block: str) -> tuple[float, float, float] | None:
    color_m = re.search(
        rf"map_color\s*{A}\s*\{{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}}", block
    )
    if not color_m:
        return 0.0, 0.0, 0.0
    try:
        return (
            float(color_m.group(1)),
            float(color_m.group(2)),
            float(color_m.group(3)),
        )
    except ValueError:
        return None


def scan_strategic_regions_file_map_color_errors(
    path: Path,
    mod_root: Path,
    vanilla: Path,
    log: object,
) -> None:
    from import_context import classify_content_path, format_import_error, line_at

    text = read_game_content(path)
    source, relative_dir, filename = classify_content_path(path, mod_root, vanilla)
    for match in re.finditer(
        block_header(r"region_[a-z0-9_]+"), text, flags=re.MULTILINE
    ):
        region = match.group(1)
        line = line_at(text, match.start())
        start = match.end() - 1
        end = _find_block_end(text, start)
        block = text[start + 1 : end]
        color_m = _MAP_COLOR_BLOCK_RE.search(block)
        if not color_m:
            continue
        tokens = color_m.group(1).strip().split()
        for i, raw in enumerate(tokens[:3], 1):
            try:
                float(raw)
            except ValueError:
                log.error(
                    format_import_error(
                        source,
                        relative_dir,
                        filename,
                        line,
                        f"解析战略区域 {region} 的 map_color",
                        f"第 {i} 个分量「{raw}」不是合法浮点数（词法错误）",
                    )
                )


def scan_strategic_regions_paths_map_color_errors(
    paths: tuple[Path, ...],
    mod_dir: Path,
    mod_root: Path,
    vanilla: Path,
    log: object,
) -> None:
    for path in ordered_merge_paths(paths, mod_dir):
        if is_empty_content_file(path):
            continue
        scan_strategic_regions_file_map_color_errors(path, mod_root, vanilla, log)


def parse_strategic_regions_paths(
    paths: tuple[Path, ...],
    mod_dir: Path | None = None,
    *,
    mod_root: Path | None = None,
    vanilla: Path | None = None,
    log: object | None = None,
) -> list[StrategicRegionRow]:
    if log is not None and mod_dir is not None and mod_root is not None and vanilla is not None:
        scan_strategic_regions_paths_map_color_errors(
            paths, mod_dir, mod_root, vanilla, log
        )
    text = _merged_block_text(paths, mod_dir, r"region_[a-z0-9_]+")
    return parse_strategic_regions_text(text)


LOCALE_DIRS: dict[str, str] = {
    "en": "localization/english",
    "bp": "localization/braz_por",
    "fr": "localization/french",
    "de": "localization/german",
    "pl": "localization/polish",
    "ru": "localization/russian",
    "es": "localization/spanish",
    "ja": "localization/japanese",
    "zh": "localization/simp_chinese",
    "ko": "localization/korean",
    "tr": "localization/turkish",
}
SUPPORTED_LOCALES: tuple[str, ...] = tuple(LOCALE_DIRS)


_LOCALE_LINE_RE = re.compile(
    r'^\s*([A-Za-z0-9_.-]+):\s*(?:(\d+)\s+)?"(.*)"\s*$',
    re.MULTILINE,
)


def parse_localization_file(path: Path) -> list[LocRow]:
    rows: list[LocRow] = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for match in _LOCALE_LINE_RE.finditer(text):
        key = match.group(1)
        if key.startswith("l_"):
            continue
        value = match.group(3).replace("\\n", "\n")
        rows.append(LocRow(key=key, text=value))
    return rows


def parse_localization_dir(directory: Path) -> list[LocRow]:
    """Load all localization YAML keys (cultures, states, buildings, PMs, etc.)."""
    merged: dict[str, str] = {}
    if not directory.is_dir():
        return []
    for path in sorted(directory.rglob("*.yml")):
        for row in parse_localization_file(path):
            merged[row.key] = row.text
    return [LocRow(key=k, text=v) for k, v in sorted(merged.items())]


def parse_localization_merged(
    mod_root: Path,
    vanilla: Path,
    *,
    locale: str = "zh",
    replace_paths: frozenset[str] | None = None,
) -> list[LocRow]:
    """Merge localization: replace_paths + filename + loc key (mod wins)."""
    rel = LOCALE_DIRS.get(locale)
    if rel is None:
        raise ValueError(f"unsupported localization locale: {locale}")
    if replace_paths is None:
        from content_paths import mod_replace_paths

        replace_paths = mod_replace_paths(mod_root)
    merged = merged_content(
        mod_root,
        rel,
        vanilla,
        replace_paths,
        file_suffix=".yml",
    )
    by_key: dict[str, str] = {}
    for path in ordered_merge_paths(merged.paths, merged.mod_dir):
        for row in parse_localization_file(path):
            by_key[row.key] = row.text
    return [LocRow(key=k, text=v) for k, v in sorted(by_key.items())]


# Primary entity localization files (also covered by rglob above).
ENTITY_LOC_REL_PATHS = (
    "cultures_l_simp_chinese.yml",
    "religion_l_simp_chinese.yml",
    "buildings_l_simp_chinese.yml",
    "production_methods_l_simp_chinese.yml",
    "companies_l_simp_chinese.yml",
    "countries_l_simp_chinese.yml",
    "hub_names_l_simp_chinese.yml",
    "map/states_l_simp_chinese.yml",
)


def resolve_provinces_png(mod_root: Path, vanilla: Path) -> tuple[Path, bytes]:
    rel = Path("map_data/provinces.png")
    mod_path = mod_root / rel
    if mod_path.is_file():
        return mod_path, mod_path.read_bytes()
    vanilla_path = vanilla / rel
    if not vanilla_path.is_file():
        raise FileNotFoundError(f"找不到 provinces.png：{vanilla_path}")
    return vanilla_path, vanilla_path.read_bytes()


def load_state_regions(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
) -> list[FlatStateRegion]:
    merged = resolve_game_content(
        mod_root, "map_data/state_regions", vanilla, replace_paths
    )
    return parse_state_regions_dir(
        paths=list(merged.paths),
        mod_dir=merged.mod_dir,
        land_only=False,
    )
