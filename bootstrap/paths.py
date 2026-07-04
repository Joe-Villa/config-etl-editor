"""Register map_db package import paths (``map_db/``, collect_origin_data)."""

from __future__ import annotations

import sys

from app_paths import bootstrap_impl_root, collect_origin_src


def register_import_paths() -> None:
    for path in (bootstrap_impl_root(), collect_origin_src()):
        entry = str(path)
        if path.is_dir() and entry not in sys.path:
            sys.path.insert(0, entry)
