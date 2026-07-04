"""Backward-compatible re-export; use ``bootstrap.build_job`` instead."""

from bootstrap.build_job import (  # noqa: F401
    BuildJob,
    BuildPhase,
    default_vanilla_game_path,
    launcher_defaults,
    launcher_gate_defaults,
)

__all__ = [
    "BuildJob",
    "BuildPhase",
    "default_vanilla_game_path",
    "launcher_defaults",
    "launcher_gate_defaults",
]
