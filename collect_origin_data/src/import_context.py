"""Format import errors with mod/vanilla file location."""

from __future__ import annotations

from pathlib import Path


def line_at(text: str, index: int) -> int:
    if index <= 0:
        return 1
    return text[:index].count("\n") + 1


def classify_content_path(
    path: Path,
    mod_root: Path,
    vanilla: Path,
) -> tuple[str, str, str]:
    """Return ``(source, relative_dir, filename)`` for a game content file."""
    resolved = path.resolve()
    mod = mod_root.resolve()
    van = vanilla.resolve()
    try:
        if resolved.is_relative_to(mod):
            rel = resolved.relative_to(mod)
            source = "mod"
        elif resolved.is_relative_to(van):
            rel = resolved.relative_to(van)
            source = "vanilla"
        else:
            return "unknown", "", resolved.name
    except ValueError:
        return "unknown", "", resolved.name

    if len(rel.parts) > 1:
        return source, "/".join(rel.parts[:-1]), rel.parts[-1]
    return source, "", rel.name


def format_import_error(
    source: str,
    relative_dir: str,
    filename: str,
    line: int,
    operation: str,
    reason: str,
) -> str:
    folder = f"{relative_dir}/" if relative_dir else ""
    return (
        f"[{source}] {folder}{filename} 第 {line} 行："
        f"正在{operation}，失败：{reason}"
    )


def format_import_warning(
    source: str,
    relative_dir: str,
    filename: str,
    line: int,
    operation: str,
    reason: str,
) -> str:
    folder = f"{relative_dir}/" if relative_dir else ""
    return (
        f"[{source}] {folder}{filename} 第 {line} 行："
        f"正在{operation}，非标准情况：{reason}"
    )
