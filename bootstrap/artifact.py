"""Bootstrap output contract: a finished sqlite file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatabaseArtifact:
    """Closed map_editor.sqlite ready for runtime ``MapSession.open``."""

    path: Path

    def __post_init__(self) -> None:
        resolved = self.path.expanduser().resolve()
        object.__setattr__(self, "path", resolved)

    def validate_exists(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(f"找不到数据库：{self.path}")
