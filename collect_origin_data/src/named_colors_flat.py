"""Parse common/named_colors into key + RGB rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from vic3_assign import VIC3_ASSIGN as A, find_block_end, read_game_content

NAMED_COLOR_KEY = r"[A-Za-z_][A-Za-z0-9_]*"
COLORS_BLOCK_RE = re.compile(rf"colors\s*{A}\s*\{{", re.MULTILINE)
NAMED_COLOR_ENTRY_RE = re.compile(
    rf"(?P<key>{NAMED_COLOR_KEY})\s*{A}\s*"
    rf"(?P<fmt>hsv360|hsv|rgb)?\s*\{{\s*"
    rf"(?P<a>[\d.]+)\s+(?P<b>[\d.]+)\s+(?P<c>[\d.]+)\s*\}}",
    re.MULTILINE,
)


@dataclass(frozen=True)
class NamedColorRow:
    key: str
    r: int
    g: int
    b: int


def _clamp_rgb(value: float) -> int:
    return max(0, min(255, round(value)))


def _rgb_from_components(a: str, b: str, c: str) -> tuple[int, int, int]:
    values = [float(a), float(b), float(c)]
    if max(values) <= 1.0:
        values = [value * 255 for value in values]
    return (_clamp_rgb(values[0]), _clamp_rgb(values[1]), _clamp_rgb(values[2]))


def _rgb_from_hsv_percent(h: str, s: str, v: str) -> tuple[int, int, int]:
    import colorsys

    red, green, blue = colorsys.hsv_to_rgb(float(h) % 1.0, float(s), float(v))
    return (_clamp_rgb(red * 255), _clamp_rgb(green * 255), _clamp_rgb(blue * 255))


def _rgb_from_hsv360(h: str, s: str, v: str) -> tuple[int, int, int]:
    import colorsys

    red, green, blue = colorsys.hsv_to_rgb(
        float(h) / 360.0,
        float(s) / 100.0,
        float(v) / 100.0,
    )
    return (_clamp_rgb(red * 255), _clamp_rgb(green * 255), _clamp_rgb(blue * 255))


def _rgb_from_named_entry(fmt: str | None, a: str, b: str, c: str) -> tuple[int, int, int]:
    if fmt == "hsv360":
        return _rgb_from_hsv360(a, b, c)
    if fmt == "hsv":
        return _rgb_from_hsv_percent(a, b, c)
    return _rgb_from_components(a, b, c)


def parse_named_colors_text(text: str) -> list[NamedColorRow]:
    match = COLORS_BLOCK_RE.search(text)
    if not match:
        return []
    block_start = match.end() - 1
    block_end = find_block_end(text, block_start)
    inner = text[block_start + 1 : block_end]
    by_key: dict[str, NamedColorRow] = {}
    for entry in NAMED_COLOR_ENTRY_RE.finditer(inner):
        key = entry.group("key")
        rgb = _rgb_from_named_entry(
            entry.group("fmt"),
            entry.group("a"),
            entry.group("b"),
            entry.group("c"),
        )
        by_key[key] = NamedColorRow(key=key, r=rgb[0], g=rgb[1], b=rgb[2])
    return list(by_key.values())


def build_named_color_lookup(
    rows: list[NamedColorRow] | tuple[NamedColorRow, ...],
) -> dict[str, tuple[int, int, int]]:
    return {row.key: (row.r, row.g, row.b) for row in rows}


def lookup_named_color(
    lookup: Mapping[str, tuple[int, int, int]],
    key: str,
) -> tuple[int, int, int] | None:
    return lookup.get(key)


def parse_named_colors_paths(
    paths: list[Path] | tuple[Path, ...],
    *,
    mod_dir: Path | None = None,
) -> list[NamedColorRow]:
    from game_content_resolver import is_empty_content_file, ordered_merge_paths

    ordered = (
        ordered_merge_paths(paths, mod_dir)
        if mod_dir is not None
        else sorted(paths, key=lambda p: p.name)
    )
    by_key: dict[str, NamedColorRow] = {}
    for path in ordered:
        if is_empty_content_file(path):
            continue
        for row in parse_named_colors_text(read_game_content(path)):
            by_key[row.key] = row
    return list(by_key.values())
