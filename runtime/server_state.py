"""Shared map session state for the HTTP server and launcher GUI."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from bootstrap.build_job import BuildJob, launcher_gate_defaults
from interactive_map.db_snapshot import restore_snapshot as restore_db_snapshot_file
from interactive_map.macro_edit_job import MacroEditJob
from runtime.loader import open_session
from runtime.session import MapSession


class MapServerState:
    """Thread-safe holder for the active MapSession (may be unloaded at startup)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: MapSession | None = None
        self.build_job = BuildJob()
        self.macro_edit_job = MacroEditJob()

    @property
    def session(self) -> MapSession | None:
        with self._lock:
            return self._session

    @property
    def db_path(self) -> Path | None:
        with self._lock:
            return None if self._session is None else self._session.db_path

    @contextmanager
    def using_session(self) -> Iterator[MapSession]:
        """Hold server + session locks for the whole sqlite operation."""
        with self._lock:
            session = self._session
            if session is None:
                raise RuntimeError("no database loaded")
            with session._lock:
                yield session

    def load(self, db_path: Path) -> MapSession:
        db_path = db_path.resolve()
        if not db_path.is_file():
            raise FileNotFoundError(f"找不到数据库：{db_path}")
        with self._lock:
            if self._session is not None:
                self._session.close()
            self._session = open_session(db_path)
            return self._session

    def close(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.close()
                self._session = None

    def restore_db_snapshot(self, snapshot_id: str) -> dict:
        with self._lock:
            if self._session is None:
                raise RuntimeError("no database loaded")
            db_path = self._session.db_path
            self._session.close()
            entry = restore_db_snapshot_file(db_path, snapshot_id)
            self._session = open_session(db_path)
            revision = self._session.refresh()
            return {
                "snapshot": entry,
                "database": str(db_path),
                "revision": revision,
            }

    def status_json(self) -> dict:
        with self._lock:
            session = self._session
            payload = {
                "loaded": session is not None,
                "database": None if session is None else str(session.db_path),
                "revision": None if session is None else session.revision,
                "defaults": launcher_gate_defaults(),
                "build": self.build_job.snapshot(),
                "macro_edit": self.macro_edit_job.snapshot(),
            }
            return payload
