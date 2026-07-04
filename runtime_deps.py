"""Register import paths for map_db ingest and runtime (Nuitka-safe)."""

from __future__ import annotations

import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from app_paths import bootstrap_impl_root, collect_origin_src


def register() -> None:
    for path in (bootstrap_impl_root(), collect_origin_src()):
        entry = str(path)
        if path.is_dir() and entry not in sys.path:
            sys.path.insert(0, entry)
    from bootstrap.paths import register_import_paths

    register_import_paths()
    import _bootstrap  # noqa: F401
    import building_flat  # noqa: F401
    import content_paths  # noqa: F401
    import game_content_resolver  # noqa: F401
    import history_source_index  # noqa: F401
    import history_states_flat  # noqa: F401
    import vic3_assign  # noqa: F401
