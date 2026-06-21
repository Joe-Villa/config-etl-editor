"""Register flat import paths and preload export_history dependencies (Nuitka-safe)."""

from __future__ import annotations

import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from app_paths import collect_origin_src, src_root


def register() -> None:
    for path in (src_root(), collect_origin_src()):
        entry = str(path)
        if path.is_dir() and entry not in sys.path:
            sys.path.insert(0, entry)
    import _bootstrap  # noqa: F401
    import building_flat  # noqa: F401
    import content_paths  # noqa: F401
    import game_content_resolver  # noqa: F401
    import history_source_index  # noqa: F401
    import history_states_flat  # noqa: F401
    import vic3_assign  # noqa: F401
