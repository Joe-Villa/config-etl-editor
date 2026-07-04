"""Parse common/country_definitions into tag + RGB color rows."""

from __future__ import annotations

import colorsys
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from vic3_assign import VIC3_ASSIGN as A, block_header, read_game_content

# Top-level country_definitions: line-start TAG = { … } (uppercase tag ids).
COUNTRY_DEFINITION_TAG_ID = r"[A-Z0-9][A-Z0-9_-]*"

COUNTRY_HEADER_RE = re.compile(
    block_header(COUNTRY_DEFINITION_TAG_ID),
    re.MULTILINE,
)
COUNTRY_BLOCK_HEADER_RE = re.compile(
    block_header(COUNTRY_DEFINITION_TAG_ID),
    re.MULTILINE,
)
DYNAMIC_COUNTRY_RE = re.compile(
    rf"dynamic_country_definition\s*{A}\s*yes",
    re.MULTILINE,
)
COLOR_KEY_RE = re.compile(rf"\bcolor\s*{A}", re.MULTILINE)
COLOR_RGB_RE = re.compile(
    rf"\bcolor\s*{A}\s*\{{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}}"
)
COLOR_RGBA_RE = re.compile(
    rf"\bcolor\s*{A}\s*\{{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}}"
)
COLOR_RGB_EXPLICIT_RE = re.compile(
    rf"color\s*{A}\s*rgb\s*\{{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}}"
)
COLOR_HSV_RE = re.compile(
    rf"color\s*{A}\s*hsv\s*\{{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}}"
)
COLOR_HSV360_RE = re.compile(
    rf"color\s*{A}\s*hsv360\s*\{{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}}"
)
COLOR_STRING_RE = re.compile(rf'\bcolor\s*{A}\s*"([A-Za-z0-9_]+)"')
NAMED_COLOR_KEY = r"[A-Za-z_][A-Za-z0-9_]*"
COLOR_NAMED_ID_RE = re.compile(
    rf"\bcolor\s*{A}\s*(?P<key>{NAMED_COLOR_KEY})(?!\s*\{{)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class CountryDefinitionRow:
    tag: str
    r: int
    g: int
    b: int


@dataclass(frozen=True)
class ColorParseResult:
    rgb: tuple[int, int, int] | None
    format: str | None = None


OFFICIAL_COUNTRY_COLOR_FORMATS = frozenset({"rgb", "hsv", "hsv360"})
DEFAULT_COUNTRY_MAP_RGB = (230, 230, 230)

NON_OFFICIAL_COLOR_FORMAT_LABELS: dict[str, str] = {
    "rgb_explicit": "显式 rgb 块 color = rgb { r g b }",
    "rgba": "RGBA 四分量 color = { r g b a }",
    "named_quoted": '命名颜色引用 color = "key"',
    "named_id": "命名颜色引用 color = key（无引号）",
}


def _find_block_end(text: str, start: int) -> int:
    from vic3_assign import find_block_end

    return find_block_end(text, start)


def _clamp_rgb(value: float) -> int:
    return max(0, min(255, round(value)))


def _rgb_from_components(a: str, b: str, c: str) -> tuple[int, int, int]:
    values = [float(a), float(b), float(c)]
    if max(values) <= 1.0:
        values = [value * 255 for value in values]
    return (_clamp_rgb(values[0]), _clamp_rgb(values[1]), _clamp_rgb(values[2]))


def _rgb_from_hsv_percent(h: str, s: str, v: str) -> tuple[int, int, int]:
    red, green, blue = colorsys.hsv_to_rgb(float(h) % 1.0, float(s), float(v))
    return (_clamp_rgb(red * 255), _clamp_rgb(green * 255), _clamp_rgb(blue * 255))


def _rgb_from_hsv360(h: str, s: str, v: str) -> tuple[int, int, int]:
    red, green, blue = colorsys.hsv_to_rgb(
        float(h) / 360.0,
        float(s) / 100.0,
        float(v) / 100.0,
    )
    return (_clamp_rgb(red * 255), _clamp_rgb(green * 255), _clamp_rgb(blue * 255))


def _parse_color_with_format(
    block: str,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> ColorParseResult:
    for pattern, parser, fmt in (
        (COLOR_HSV360_RE, _rgb_from_hsv360, "hsv360"),
        (COLOR_HSV_RE, _rgb_from_hsv_percent, "hsv"),
        (COLOR_RGB_EXPLICIT_RE, _rgb_from_components, "rgb_explicit"),
        (COLOR_RGBA_RE, _rgb_from_components, "rgba"),
        (COLOR_RGB_RE, _rgb_from_components, "rgb"),
    ):
        match = pattern.search(block)
        if match:
            return ColorParseResult(rgb=parser(match.group(1), match.group(2), match.group(3)), format=fmt)
    if named_colors is not None:
        str_match = COLOR_STRING_RE.search(block)
        if str_match:
            rgb = named_colors.get(str_match.group(1))
            if rgb is not None:
                return ColorParseResult(rgb=rgb, format="named_quoted")
        id_match = COLOR_NAMED_ID_RE.search(block)
        if id_match:
            rgb = named_colors.get(id_match.group("key"))
            if rgb is not None:
                return ColorParseResult(rgb=rgb, format="named_id")
    return ColorParseResult(rgb=None, format=None)


def _parse_color(
    block: str,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> tuple[int, int, int] | None:
    return _parse_color_with_format(block, named_colors).rgb


def _non_official_color_warning_reason(fmt: str) -> str:
    label = NON_OFFICIAL_COLOR_FORMAT_LABELS.get(fmt, fmt)
    return f"color 使用非官方写法（{label}），已按语义推断解析为地图颜色"


def _missing_color_fallback_reason(reason: str) -> str:
    r, g, b = DEFAULT_COUNTRY_MAP_RGB
    return f"{reason}，已使用游戏默认地图颜色 {r}, {g}, {b}"


def _warn_missing_country_color(
    log: object,
    *,
    source: str,
    relative_dir: str,
    filename: str,
    line: int,
    tag: str,
    reason: str,
) -> None:
    from import_context import format_import_warning

    warn = getattr(log, "warn", None)
    if warn is None:
        return
    warn(
        format_import_warning(
            source,
            relative_dir,
            filename,
            line,
            f"解析国家定义块（{tag}）",
            _missing_color_fallback_reason(reason),
        )
    )


def resolve_country_definition_map_color(
    block: str,
    *,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> tuple[tuple[int, int, int] | None, str | None]:
    """Return map RGB and optional fallback reason (None rgb = skip row)."""
    if DYNAMIC_COUNTRY_RE.search(block):
        parsed = _parse_color_with_format(block, named_colors)
        if parsed.rgb is None:
            return None, None
        return parsed.rgb, None

    parsed = _parse_color_with_format(block, named_colors)
    if parsed.rgb is not None:
        return parsed.rgb, None
    reason = _country_color_error_reason(block, named_colors)
    if reason is None:
        return None, None
    return DEFAULT_COUNTRY_MAP_RGB, reason


def _warn_non_official_country_color(
    log: object,
    *,
    source: str,
    relative_dir: str,
    filename: str,
    line: int,
    tag: str,
    fmt: str,
) -> None:
    from import_context import format_import_warning

    warn = getattr(log, "warn", None)
    if warn is None:
        return
    warn(
        format_import_warning(
            source,
            relative_dir,
            filename,
            line,
            f"解析国家定义块（{tag}）",
            _non_official_color_warning_reason(fmt),
        )
    )


def _unknown_named_color_reason(
    block: str,
    named_colors: Mapping[str, tuple[int, int, int]] | None,
) -> str | None:
    if named_colors is None:
        return None
    str_match = COLOR_STRING_RE.search(block)
    if str_match:
        key = str_match.group(1)
        if key not in named_colors:
            return f'color 引用未知命名颜色 "{key}"'
    id_match = COLOR_NAMED_ID_RE.search(block)
    if id_match:
        key = id_match.group("key")
        if key not in named_colors:
            return f'color 引用未知命名颜色 "{key}"'
    return None


def _country_color_error_reason(
    block: str,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> str | None:
    """Return a parse failure reason, or None when color is optional / valid."""
    if DYNAMIC_COUNTRY_RE.search(block):
        return None
    if _parse_color(block, named_colors) is not None:
        return None
    if COLOR_KEY_RE.search(block):
        unknown_named = _unknown_named_color_reason(block, named_colors)
        if unknown_named is not None:
            return unknown_named
        return "color 字段存在但无法解析（格式错误或分量非法）"
    return "缺少 color 字段"


def scan_country_definitions_file_errors(
    path: Path,
    mod_root: Path,
    vanilla: Path,
    log: object,
    *,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> None:
    """Log import errors for country_definitions blocks (brace / color parse)."""
    from import_context import classify_content_path, format_import_error, line_at

    text = read_game_content(path)
    source, relative_dir, filename = classify_content_path(path, mod_root, vanilla)
    inner_header_re = re.compile(
        block_header(COUNTRY_DEFINITION_TAG_ID),
        flags=re.MULTILINE,
    )
    for match in COUNTRY_BLOCK_HEADER_RE.finditer(text):
        tag = match.group(1)
        block_start = match.end() - 1
        line = line_at(text, match.start())
        try:
            block_end = _find_block_end(text, block_start)
        except ValueError:
            log.error(
                format_import_error(
                    source,
                    relative_dir,
                    filename,
                    line,
                    f"解析国家定义块（{tag}）",
                    "括号不匹配，存在未闭合的 { } 块",
                )
            )
            continue
        block = text[block_start + 1 : block_end]
        color_reason = _country_color_error_reason(block, named_colors)
        if color_reason is not None:
            _warn_missing_country_color(
                log,
                source=source,
                relative_dir=relative_dir,
                filename=filename,
                line=line,
                tag=tag,
                reason=color_reason,
            )
        else:
            parsed = _parse_color_with_format(block, named_colors)
            if (
                parsed.rgb is not None
                and parsed.format is not None
                and parsed.format not in OFFICIAL_COUNTRY_COLOR_FORMATS
            ):
                _warn_non_official_country_color(
                    log,
                    source=source,
                    relative_dir=relative_dir,
                    filename=filename,
                    line=line,
                    tag=tag,
                    fmt=parsed.format,
                )
        inner = text[block_start + 1 : block_end]
        swallowed = [m.group(1) for m in inner_header_re.finditer(inner)]
        if not swallowed:
            continue
        preview = ", ".join(swallowed[:5])
        if len(swallowed) > 5:
            preview = f"{preview} 等 {len(swallowed)} 个"
        log.error(
            format_import_error(
                source,
                relative_dir,
                filename,
                line,
                f"解析国家定义块（{tag}）",
                f"括号不匹配，块内包含本应独立的国家定义：{preview}",
            )
        )


def scan_country_definitions_paths_errors(
    paths: list[Path] | tuple[Path, ...],
    mod_dir: Path,
    mod_root: Path,
    vanilla: Path,
    log: object,
    *,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> None:
    from game_content_resolver import is_empty_content_file, ordered_merge_paths

    for path in ordered_merge_paths(paths, mod_dir):
        if is_empty_content_file(path):
            continue
        scan_country_definitions_file_errors(
            path, mod_root, vanilla, log, named_colors=named_colors
        )


def parse_country_definitions_text(
    text: str,
    *,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
    warnings: list[str] | None = None,
) -> list[CountryDefinitionRow]:
    rows: list[CountryDefinitionRow] = []
    for match in COUNTRY_HEADER_RE.finditer(text):
        tag = match.group(1)
        block_start = match.end() - 1
        block_end = _find_block_end(text, block_start)
        block = text[block_start + 1 : block_end]
        rgb, fallback_reason = resolve_country_definition_map_color(
            block,
            named_colors=named_colors,
        )
        if rgb is None:
            continue
        parsed = _parse_color_with_format(block, named_colors)
        if fallback_reason is not None:
            if warnings is not None:
                warnings.append(
                    f"国家定义 {tag}：{_missing_color_fallback_reason(fallback_reason)}"
                )
        elif (
            warnings is not None
            and parsed.format is not None
            and parsed.format not in OFFICIAL_COUNTRY_COLOR_FORMATS
        ):
            warnings.append(
                f"国家定义 {tag}：{_non_official_color_warning_reason(parsed.format)}"
            )
        r, g, b = rgb
        rows.append(CountryDefinitionRow(tag=tag, r=r, g=g, b=b))
    return rows


def _merge_definition_rows(
    by_tag: dict[str, CountryDefinitionRow],
    rows: list[CountryDefinitionRow],
) -> None:
    for row in rows:
        by_tag[row.tag] = row


def parse_country_definitions_paths(
    paths: list[Path] | tuple[Path, ...],
    *,
    mod_dir: Path | None = None,
    mod_root: Path | None = None,
    vanilla: Path | None = None,
    log: object | None = None,
    named_colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> list[CountryDefinitionRow]:
    from game_content_resolver import is_empty_content_file, read_merged_paradox_blocks

    if mod_dir is not None:
        if log is not None and mod_root is not None and vanilla is not None:
            scan_country_definitions_paths_errors(
                paths,
                mod_dir,
                mod_root,
                vanilla,
                log,
                named_colors=named_colors,
            )
        text = read_merged_paradox_blocks(
            paths,
            mod_dir,
            COUNTRY_DEFINITION_TAG_ID,
        )
        return parse_country_definitions_text(text, named_colors=named_colors)

    by_tag: dict[str, CountryDefinitionRow] = {}

    def ingest(path: Path) -> None:
        if is_empty_content_file(path):
            return
        text = read_game_content(path)
        _merge_definition_rows(
            by_tag, parse_country_definitions_text(text, named_colors=named_colors)
        )

    for path in paths:
        ingest(path)

    return list(by_tag.values())


def validate_active_tags_have_definitions(
    active_tags: set[str],
    definitions: list[CountryDefinitionRow],
) -> None:
    by_tag = {row.tag: row for row in definitions}
    missing = sorted(tag for tag in active_tags if tag not in by_tag)
    if missing:
        joined = ", ".join(missing)
        raise ValueError(
            f"活跃国家 tag 缺少 country_definitions 定义（含颜色）：{joined}"
        )
