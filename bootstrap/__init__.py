"""Bootstrap phase: orchestrate ``map_db`` and hand off sqlite to runtime.

The handoff contract to runtime is a closed sqlite file on disk (see ``DatabaseArtifact``).
"""

from __future__ import annotations

from bootstrap.artifact import DatabaseArtifact
from bootstrap.build_job import BuildJob, launcher_defaults, launcher_gate_defaults
from bootstrap.paths import register_import_paths

__all__ = [
    "BuildJob",
    "DatabaseArtifact",
    "build_map_db",
    "launcher_defaults",
    "launcher_gate_defaults",
    "register_import_paths",
    "resolve_build_output_path",
]


def build_map_db(*args, **kwargs):
    register_import_paths()
    from build_db import build_map_db as _build_map_db

    return _build_map_db(*args, **kwargs)


def resolve_build_output_path(*args, **kwargs):
    register_import_paths()
    from build_db import resolve_build_output_path as _resolve

    return _resolve(*args, **kwargs)
