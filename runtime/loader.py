"""Load a database artifact into a runtime session."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.session import MapSession


def open_session(db_path: Path) -> MapSession:
    """Open ``map_editor.sqlite``; input is always a filesystem path."""
    from runtime.session import MapSession

    return MapSession.open(db_path)
