"""Resolve package root in development and Nuitka standalone builds."""

from __future__ import annotations

import sys
from pathlib import Path


def _is_compiled() -> bool:
    if getattr(sys, "frozen", False):
        return True
    main = sys.modules.get("__main__")
    return main is not None and getattr(main, "__compiled__", None) is not None


def package_root() -> Path:
    """Directory containing interactive_map/, src/, and (when bundled) collect_origin_data/."""
    if _is_compiled():
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent
    if (here / "interactive_map").is_dir():
        return here
    candidate = Path(sys.argv[0]).resolve().parent
    if (candidate / "interactive_map").is_dir():
        return candidate
    return here


def repo_root() -> Path:
    """Parent of package_root in dev; same as package_root when collect_origin_data is bundled."""
    root = package_root()
    sibling = root.parent / "collect_origin_data" / "src"
    if sibling.is_dir():
        return root.parent
    return root


def collect_origin_src() -> Path:
    bundled = package_root() / "collect_origin_data" / "src"
    if bundled.is_dir():
        return bundled
    return repo_root() / "collect_origin_data" / "src"


def interactive_map_root() -> Path:
    return package_root() / "interactive_map"


def viewer_root() -> Path:
    return interactive_map_root() / "viewer"


def src_root() -> Path:
    return package_root() / "src"


def install_root() -> Path:
    """Parent of app/ — portable 包中为 exe 所在目录。"""
    return package_root().resolve().parent


def default_save_dir() -> Path:
    return install_root() / "save"


def default_save_sqlite() -> Path:
    return default_save_dir() / "map_editor.sqlite"
