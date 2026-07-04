"""Paradox script assignment and shared game-content text preprocessing."""

import re
from pathlib import Path

VIC3_ASSIGN = r"(?:\?=|=)"
REPLACE_OR_CREATE_PREFIX = r"(?:REPLACE_OR_CREATE:)?"


def block_header(id_pattern: str, *, line_prefix: str = "") -> str:
    """Top-level object block header; supports optional REPLACE_OR_CREATE: prefix."""
    return rf"^\s*{line_prefix}{REPLACE_OR_CREATE_PREFIX}({id_pattern})\s*{VIC3_ASSIGN}\s*\{{"


def mask_line_comments(text: str) -> str:
    """Mask ``#`` through end-of-line (keep length) so parsers ignore Paradox comments.

    Standard preprocessing for all game ``.txt`` content. Localization YAML must not
    use this — keys/values may contain ``#`` inside quoted strings.
    """
    parts: list[str] = []
    pos = 0
    while pos < len(text):
        hash_at = text.find("#", pos)
        if hash_at < 0:
            parts.append(text[pos:])
            break
        parts.append(text[pos:hash_at])
        line_end = text.find("\n", hash_at)
        if line_end < 0:
            parts.append(" " * (len(text) - hash_at))
            break
        parts.append(" " * (line_end - hash_at))
        parts.append("\n")
        pos = line_end + 1
    return "".join(parts)


def prepare_game_content(text: str) -> str:
    """Return game content text with line comments masked (see ``mask_line_comments``)."""
    return mask_line_comments(text)


def read_game_content(path: Path) -> str:
    """Read a game content file with line comments masked."""
    return prepare_game_content(
        path.read_text(encoding="utf-8-sig", errors="replace")
    )


def strip_line_comments(text: str) -> str:
    """Remove ``#`` through end-of-line. Prefer ``prepare_game_content`` for parsing."""
    return re.sub(r"(?m)#.*$", "", text)


def find_block_end(text: str, start: int) -> int:
    """Index of ``}`` that closes the ``{`` at ``start``; ignores ``#`` line comments."""
    masked = mask_line_comments(text)
    depth = 0
    for j in range(start, len(masked)):
        ch = masked[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return j
    raise ValueError(f"第 {start} 个字符处存在未闭合的 {{}} 块")


def brace_depth_at(text: str, index: int) -> int:
    """Brace nesting depth immediately before ``index`` (line comments masked)."""
    depth = 0
    for ch in mask_line_comments(text[:index]):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth


def iter_top_level_block_matches(
    text: str,
    id_pattern: str,
    *,
    line_prefix: str = "",
):
    """Yield block-header regex matches at brace depth 0 only (skip nested blocks)."""
    header_re = re.compile(
        block_header(id_pattern, line_prefix=line_prefix),
        re.MULTILINE,
    )
    for match in header_re.finditer(text):
        if brace_depth_at(text, match.start()) == 0:
            yield match
