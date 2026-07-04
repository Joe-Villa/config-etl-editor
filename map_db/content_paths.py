"""Resolve mod vs vanilla content paths (incl. .metadata replace_paths)."""

from __future__ import annotations

from pathlib import Path

from game_content_resolver import (
    MergedContent,
    load_mod_replace_paths,
    read_merged_paradox_blocks,
    resolve_merged_content,
)

# Block id patterns for step-3 merge (mod overrides vanilla per logical block).
# Third tuple element: combine inner content when the same id appears in multiple files.
# New folders should register here and use ``merged_paradox_text``.
PARADOX_BLOCK_SPECS: dict[str, tuple[str, str, bool]] = {
    "common/religions": (r"[a-z][a-z0-9_]*", "", False),
    "common/cultures": (r"[a-z][a-z0-9_]*", "", False),
    "common/building_groups": (r"bg_[a-z0-9_]+", "", False),
    "common/buildings": (r"building_[a-z0-9_]+", "", False),
    "common/production_method_groups": (r"pmg_[a-z0-9_]+", "", False),
    "common/company_types": (r"company_[a-z0-9_]+", "", False),
    "common/strategic_regions": (r"region_[a-z0-9_]+", "", False),
    "common/country_definitions": (r"[A-Z0-9][A-Z0-9_-]*", "", False),
    "map_data/state_regions": (r"STATE_\w+", "", False),
    "common/history/states": (r"STATE_\w+", "s:", False),
    "common/history/pops": (r"STATE_\w+", "s:", True),
    "common/history/buildings": (r"STATE_\w+", "s:", True),
}


def mod_replace_paths(mod_root: Path) -> frozenset[str]:
    """Read replace_paths from mod `.metadata/metadata.json`; empty if missing."""
    return load_mod_replace_paths(mod_root)


def resolve_game_content(
    mod_root: Path,
    relative: str,
    vanilla: Path,
    replace_paths: frozenset[str],
    *,
    file_suffix: str = ".txt",
) -> MergedContent:
    return resolve_merged_content(
        mod_root,
        relative,
        vanilla,
        replace_paths=replace_paths,
        file_suffix=file_suffix,
    )


def merged_content(
    mod_root: Path,
    relative: str,
    vanilla: Path,
    replace_paths: frozenset[str],
    *,
    file_suffix: str = ".txt",
) -> MergedContent:
    """Steps 1–2: resolve which physical files participate."""
    return resolve_game_content(
        mod_root,
        relative,
        vanilla,
        replace_paths,
        file_suffix=file_suffix,
    )


def merged_paradox_text(
    mod_root: Path,
    relative: str,
    vanilla: Path,
    replace_paths: frozenset[str],
    *,
    id_pattern: str | None = None,
    line_prefix: str = "",
    file_suffix: str = ".txt",
) -> str:
    """Steps 1–3 for Paradox ``id = { ... }`` folders."""
    if id_pattern is None:
        spec = PARADOX_BLOCK_SPECS.get(normalize_relative(relative))
        if spec is None:
            raise ValueError(f"未注册 Paradox 块合并规则：{relative}")
        id_pattern, line_prefix, combine_duplicates = spec
    merged = merged_content(
        mod_root,
        relative,
        vanilla,
        replace_paths,
        file_suffix=file_suffix,
    )
    return read_merged_paradox_blocks(
        merged.paths,
        merged.mod_dir,
        id_pattern,
        line_prefix=line_prefix,
        combine_duplicates=combine_duplicates,
    )


def merged_history_buildings_text(
    mod_root: Path,
    vanilla: Path,
    replace_paths: frozenset[str],
) -> str:
    """Merge ``s:STATE_*`` blocks and wrap as ``BUILDINGS = { ... }``."""
    from game_content_resolver import merge_paradox_blocks

    merged = merged_content(
        mod_root,
        "common/history/buildings",
        vanilla,
        replace_paths,
    )
    id_pattern, line_prefix, combine_duplicates = PARADOX_BLOCK_SPECS[
        "common/history/buildings"
    ]
    blocks = merge_paradox_blocks(
        merged.paths,
        merged.mod_dir,
        id_pattern,
        line_prefix=line_prefix,
        combine_duplicates=combine_duplicates,
    )
    if not blocks:
        return ""
    inner = "\n".join(blocks.values())
    return f"BUILDINGS = {{\n{inner}\n}}\n"


def normalize_relative(relative: str) -> str:
    from game_content_resolver import normalize_relative_path

    return normalize_relative_path(relative)
