"""Resolve mod vs vanilla game content directories.

Paradox ``.txt`` folder merge (file + block level), per folder:

1. If ``replace_paths`` in mod metadata lists this folder → only mod files.
2. Else per filename: mod file replaces vanilla file with the same name.
3. For each top-level logical block id, later sources override earlier:
   all vanilla files (sorted by name), then all mod files (sorted by name);
   mod blocks always beat vanilla blocks with the same id.

Step 1–2 are ``resolve_merged_content`` / ``merge_txt_paths``.
Step 3 is ``read_merged_paradox_blocks`` (override by default).

For ``common/history/pops`` and ``common/history/buildings``, the same
``s:STATE_*`` id may appear in multiple files; use ``combine_duplicates=True``
to append inner script instead of replacing the whole block. History states
use ``merge_history_states_blocks`` (replace when ``create_state`` present).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator

from vic3_assign import block_header, find_block_end, read_game_content


class ContentSource(str, Enum):
    VANILLA = "vanilla"
    MOD = "mod"
    MOD_PART = "mod_part"
    DERIVED = "derived"


MOD_METADATA_PATH = Path(".metadata") / "metadata.json"


def normalize_relative_path(relative: str) -> str:
    return relative.strip().strip("/")


def load_mod_replace_paths(mod_root: Path) -> frozenset[str]:
    """Read replace_paths from mod `.metadata/metadata.json`.

    Missing metadata file is treated as no replace_paths.
    """
    path = mod_root / MOD_METADATA_PATH
    if not path.is_file():
        return frozenset()
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    custom = payload.get("game_custom_data")
    if not isinstance(custom, dict):
        return frozenset()
    raw = custom.get("replace_paths")
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(
        normalize_relative_path(item)
        for item in raw
        if isinstance(item, str) and item.strip()
    )


def strip_comments(text: str) -> str:
    """Mask line comments (legacy name; see ``prepare_game_content``)."""
    from vic3_assign import prepare_game_content

    return prepare_game_content(text)


def is_empty_content_file(path: Path) -> bool:
    return not read_game_content(path).strip()


def list_txt_files(directory: Path) -> list[Path]:
    return list_content_files(directory, suffix=".txt")


def list_content_files(directory: Path, *, suffix: str) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix == suffix
    )


def _files_by_name(directory: Path, suffix: str) -> dict[str, Path]:
    return {path.name: path for path in list_content_files(directory, suffix=suffix)}


def _txt_files_by_name(directory: Path) -> dict[str, Path]:
    return _files_by_name(directory, ".txt")


def merge_content_paths(
    mod_dir: Path,
    vanilla_dir: Path,
    *,
    suffix: str = ".txt",
) -> tuple[list[Path], ContentSource]:
    """Merge mod and vanilla files at the same relative path (by filename)."""
    vanilla_files = _files_by_name(vanilla_dir, suffix)
    mod_files = _files_by_name(mod_dir, suffix)

    if not mod_files:
        return list(vanilla_files.values()), ContentSource.VANILLA

    merged = dict(vanilla_files)
    merged.update(mod_files)

    vanilla_names = set(vanilla_files)
    mod_names = set(mod_files)
    if mod_names >= vanilla_names:
        source = ContentSource.MOD
    else:
        source = ContentSource.MOD_PART

    return sorted(merged.values(), key=lambda p: p.name), source


def merge_txt_paths(
    mod_dir: Path,
    vanilla_dir: Path,
) -> tuple[list[Path], ContentSource]:
    return merge_content_paths(mod_dir, vanilla_dir, suffix=".txt")


@dataclass(frozen=True)
class MergedContent:
    paths: tuple[Path, ...]
    source: ContentSource
    content_dir: Path
    mod_dir: Path
    vanilla_dir: Path


def resolve_merged_content(
    mod_root: Path,
    relative: str,
    vanilla_game: Path,
    *,
    force_vanilla: bool = False,
    replace_paths: frozenset[str] | None = None,
    file_suffix: str = ".txt",
) -> MergedContent:
    normalized_relative = normalize_relative_path(relative)
    mod_dir = mod_root / normalized_relative
    vanilla_dir = vanilla_game / normalized_relative

    def list_paths(directory: Path) -> list[Path]:
        return list_content_files(directory, suffix=file_suffix)

    if force_vanilla:
        paths = list_paths(vanilla_dir)
        return MergedContent(
            paths=tuple(paths),
            source=ContentSource.VANILLA,
            content_dir=vanilla_dir,
            mod_dir=mod_dir,
            vanilla_dir=vanilla_dir,
        )

    if replace_paths and normalized_relative in replace_paths:
        paths = list_paths(mod_dir)
        return MergedContent(
            paths=tuple(paths),
            source=ContentSource.MOD,
            content_dir=mod_dir,
            mod_dir=mod_dir,
            vanilla_dir=vanilla_dir,
        )

    paths, source = merge_content_paths(mod_dir, vanilla_dir, suffix=file_suffix)
    if mod_dir.is_dir() and _files_by_name(mod_dir, file_suffix):
        content_dir = mod_dir
    else:
        content_dir = vanilla_dir

    return MergedContent(
        paths=tuple(paths),
        source=source,
        content_dir=content_dir,
        mod_dir=mod_dir,
        vanilla_dir=vanilla_dir,
    )


def resolve_content_dir(
    mod_root: Path,
    relative: str,
    vanilla_game: Path,
    *,
    force_vanilla: bool = False,
) -> tuple[Path, ContentSource]:
    """Backward-compatible wrapper returning a representative directory."""
    merged = resolve_merged_content(
        mod_root,
        relative,
        vanilla_game,
        force_vanilla=force_vanilla,
    )
    return merged.content_dir, merged.source


def path_is_from_mod(path: Path, mod_dir: Path) -> bool:
    try:
        path.resolve().relative_to(mod_dir.resolve())
        return True
    except ValueError:
        return False


def split_merged_paths(
    paths: list[Path] | tuple[Path, ...],
    mod_dir: Path,
) -> tuple[list[Path], list[Path]]:
    """Split merged file lists into vanilla-sourced and mod-sourced paths."""
    vanilla_paths: list[Path] = []
    mod_paths: list[Path] = []
    for path in paths:
        if path_is_from_mod(path, mod_dir):
            mod_paths.append(path)
        else:
            vanilla_paths.append(path)
    return vanilla_paths, mod_paths


def read_txt_paths(paths: list[Path] | tuple[Path, ...], *, skip_empty: bool = True) -> str:
    chunks: list[str] = []
    for path in paths:
        if skip_empty and is_empty_content_file(path):
            continue
        chunks.append(read_game_content(path))
    return "\n".join(chunks)


def read_txt_paths_mod_over_vanilla(
    paths: list[Path] | tuple[Path, ...],
    mod_dir: Path,
    *,
    skip_empty: bool = True,
) -> str:
    """Concatenate vanilla files first, then mod files (no per-block dedup)."""
    vanilla_paths, mod_paths = split_merged_paths(paths, mod_dir)
    return read_txt_paths(vanilla_paths, skip_empty=skip_empty) + "\n" + read_txt_paths(
        mod_paths,
        skip_empty=skip_empty,
    )


def ordered_merge_paths(
    paths: list[Path] | tuple[Path, ...],
    mod_dir: Path,
) -> list[Path]:
    """Vanilla paths first (by filename), then mod paths (by filename)."""
    vanilla_paths, mod_paths = split_merged_paths(paths, mod_dir)
    return sorted(vanilla_paths, key=lambda p: p.name) + sorted(mod_paths, key=lambda p: p.name)


def iter_paradox_blocks(
    text: str,
    id_pattern: str,
    *,
    line_prefix: str = "",
) -> Iterator[tuple[str, str]]:
    """Yield ``(block_id, full_block_text)`` for top-level Paradox object blocks."""
    header_re = re.compile(
        block_header(id_pattern, line_prefix=line_prefix),
        re.MULTILINE,
    )
    for match in header_re.finditer(text):
        key = match.group(1)
        start_brace = match.end() - 1
        end = find_block_end(text, start_brace)
        yield key, text[match.start() : end + 1]


def paradox_block_inner(full_block: str) -> str:
    """Return the body inside the outermost ``{ ... }`` of a paradox block."""
    inner_start = full_block.index("{") + 1
    inner_end = full_block.rfind("}")
    return full_block[inner_start:inner_end]


def append_paradox_block_inner(full_block: str, additive_inner: str) -> str:
    """Append additive inner script before the closing ``}`` of a paradox block."""
    extra = additive_inner.strip()
    if not extra:
        return full_block
    close_at = full_block.rfind("}")
    if close_at < 0:
        return full_block
    return full_block[:close_at] + "\n" + extra + "\n" + full_block[close_at:]


def merge_paradox_blocks(
    paths: list[Path] | tuple[Path, ...],
    mod_dir: Path,
    id_pattern: str,
    *,
    line_prefix: str = "",
    skip_empty: bool = True,
    combine_duplicates: bool = False,
) -> dict[str, str]:
    """Merge block ids across files; mod files override vanilla (see module docstring).

    When ``combine_duplicates`` is true, repeated ids append inner content instead
    of replacing the whole block (used for history pops/buildings).
    """
    blocks: dict[str, str] = {}
    for path in ordered_merge_paths(paths, mod_dir):
        if skip_empty and is_empty_content_file(path):
            continue
        text = read_game_content(path)
        for key, block in iter_paradox_blocks(
            text, id_pattern, line_prefix=line_prefix
        ):
            if combine_duplicates and key in blocks:
                blocks[key] = append_paradox_block_inner(
                    blocks[key],
                    paradox_block_inner(block),
                )
            else:
                blocks[key] = block
    return blocks


def read_merged_paradox_blocks(
    paths: list[Path] | tuple[Path, ...],
    mod_dir: Path,
    id_pattern: str,
    *,
    line_prefix: str = "",
    skip_empty: bool = True,
    combine_duplicates: bool = False,
) -> str:
    """Merged paradox source text with one block per logical id."""
    blocks = merge_paradox_blocks(
        paths,
        mod_dir,
        id_pattern,
        line_prefix=line_prefix,
        skip_empty=skip_empty,
        combine_duplicates=combine_duplicates,
    )
    if not blocks:
        return ""
    return "\n".join(blocks.values()) + "\n"


def read_txt_dir(directory: Path, *, skip_empty: bool = True) -> str:
    return read_txt_paths(list_txt_files(directory), skip_empty=skip_empty)
