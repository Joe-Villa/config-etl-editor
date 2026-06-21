"""Add collect_origin_data parsers to import path."""

from __future__ import annotations

import sys
from pathlib import Path


def _collect_src() -> Path:
    try:
        from app_paths import collect_origin_src

        return collect_origin_src()
    except ImportError:
        return Path(__file__).resolve().parents[2] / "collect_origin_data" / "src"


_COLLECT_SRC = _collect_src()
if _COLLECT_SRC.is_dir() and str(_COLLECT_SRC) not in sys.path:
    sys.path.insert(0, str(_COLLECT_SRC))
