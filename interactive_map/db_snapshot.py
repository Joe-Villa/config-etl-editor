"""Full-database snapshots for rollback (separate from per-edit undo in edit/snapshot.py)."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

INDEX_VERSION = 1
INITIAL_SNAPSHOT_LABEL = "初始建库"


def _sqlite_sidecar_paths(db_path: Path) -> tuple[Path, Path]:
    return Path(f"{db_path}-wal"), Path(f"{db_path}-shm")


def snapshots_dir(db_path: Path) -> Path:
    return Path(f"{db_path}.snapshots")


def _index_path(db_path: Path) -> Path:
    return snapshots_dir(db_path) / "index.json"


def _load_index(db_path: Path) -> dict:
    path = _index_path(db_path)
    if not path.is_file():
        return {
            "version": INDEX_VERSION,
            "database": str(db_path.resolve()),
            "snapshots": [],
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("snapshots"), list):
        raise ValueError("快照索引损坏")
    return data


def _save_index(db_path: Path, index: dict) -> None:
    directory = snapshots_dir(db_path)
    directory.mkdir(parents=True, exist_ok=True)
    index["version"] = INDEX_VERSION
    index["database"] = str(db_path.resolve())
    _index_path(db_path).write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _snapshot_file(db_path: Path, snapshot_id: str) -> Path:
    return snapshots_dir(db_path) / f"{snapshot_id}.sqlite"


def _new_snapshot_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _default_snapshot_label() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _checkpoint(conn: sqlite3.Connection | None, db_path: Path) -> None:
    if conn is not None:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
        return
    conn2 = sqlite3.connect(db_path)
    try:
        conn2.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn2.commit()
    finally:
        conn2.close()


def create_snapshot(
    db_path: Path,
    *,
    label: str = "",
    auto: bool = False,
    conn: sqlite3.Connection | None = None,
) -> dict:
    db_path = db_path.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"找不到数据库：{db_path}")

    _checkpoint(conn, db_path)

    index = _load_index(db_path)
    base_id = _new_snapshot_id()
    snapshot_id = base_id
    suffix = 0
    while _snapshot_file(db_path, snapshot_id).exists():
        suffix += 1
        snapshot_id = f"{base_id}_{suffix:02d}"

    dest = _snapshot_file(db_path, snapshot_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, dest)

    entry = {
        "id": snapshot_id,
        "label": label.strip() or _default_snapshot_label(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auto": bool(auto),
    }
    index["snapshots"].append(entry)
    _save_index(db_path, index)
    return entry


def create_initial_snapshot(db_path: Path) -> dict:
    return create_snapshot(db_path, label=INITIAL_SNAPSHOT_LABEL, auto=True)


def list_snapshots(db_path: Path) -> list[dict]:
    db_path = db_path.resolve()
    index = _load_index(db_path)
    return list(index.get("snapshots", []))


def get_snapshot(db_path: Path, snapshot_id: str) -> dict:
    for entry in list_snapshots(db_path):
        if entry["id"] == snapshot_id:
            return entry
    raise FileNotFoundError(f"找不到快照：{snapshot_id}")


def restore_snapshot(db_path: Path, snapshot_id: str) -> dict:
    """Replace live database with a snapshot copy. Caller must close open connections."""
    db_path = db_path.resolve()
    src = _snapshot_file(db_path, snapshot_id)
    if not src.is_file():
        raise FileNotFoundError(f"找不到快照文件：{snapshot_id}")
    entry = get_snapshot(db_path, snapshot_id)

    for path in (db_path, *_sqlite_sidecar_paths(db_path)):
        if path.is_file():
            path.unlink()

    shutil.copy2(src, db_path)
    return entry
