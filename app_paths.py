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
    """Directory containing map_db/, bootstrap/, runtime/, interactive_map/."""
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


def bootstrap_root() -> Path:
    return package_root() / "bootstrap"


def runtime_root() -> Path:
    return package_root() / "runtime"


def map_db_root() -> Path:
    """Map editor sqlite build package (parse game content → map_editor.sqlite)."""
    return package_root() / "map_db"


def bootstrap_impl_root() -> Path:
    """Alias for map_db_root (used by bootstrap path registration)."""
    return map_db_root()


def build_root() -> Path:
    """Deprecated alias for map_db_root."""
    return map_db_root()


def viewer_root() -> Path:
    return interactive_map_root() / "viewer"


def src_root() -> Path:
    """Deprecated alias for map_db_root."""
    return map_db_root()


def install_root() -> Path:
    """Parent of app/ — portable 包中为 exe 所在目录。"""
    return package_root().resolve().parent


def default_save_dir() -> Path:
    return install_root() / "save"


def default_save_sqlite() -> Path:
    return default_save_dir() / "map_editor.sqlite"
