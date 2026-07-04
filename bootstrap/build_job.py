"""Background map_editor.sqlite build job for the web launcher."""

from __future__ import annotations

import io
import threading
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from app_paths import default_save_sqlite, package_root

from bootstrap.paths import register_import_paths

if TYPE_CHECKING:
    from runtime.server_state import MapServerState

BuildPhase = Literal["idle", "running", "done", "error"]

WINDOWS_VANILLA_GAME = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game"
)


def default_vanilla_game_path() -> str:
    """Default Victoria 3 ``game`` folder on a typical Windows Steam install."""
    return str(WINDOWS_VANILLA_GAME)


def launcher_defaults() -> dict[str, str]:
    root = package_root().resolve()
    return {
        "cwd": str(root),
        "output": str(default_save_sqlite()),
        "vanilla": default_vanilla_game_path(),
    }


def launcher_gate_defaults() -> dict[str, str]:
    """Defaults exposed to the web launcher (paths already resolved)."""
    defaults = launcher_defaults()
    return {
        "cwd": defaults["cwd"],
        "output": defaults["output"],
        "vanilla": defaults["vanilla"],
    }


@dataclass
class BuildJob:
    phase: BuildPhase = "idle"
    log: list[str] = field(default_factory=list)
    output: Path | None = None
    error: str | None = None
    progress_percent: int = 0
    progress_message: str = ""
    progress_done: int = 0
    progress_total: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def report_progress(self, done: int, total: int, label_zh: str) -> None:
        with self._lock:
            total = max(0, int(total))
            done = max(0, min(int(done), total)) if total else 0
            self.progress_total = total
            self.progress_done = done
            self.progress_percent = int(done * 100 / total) if total else 0
            self.progress_message = f"正在绘制{label_zh}图片"

    def report_build_progress(self, done: int, total: int, message: str) -> None:
        with self._lock:
            total = max(0, int(total))
            done = max(0, min(int(done), total)) if total else 0
            self.progress_total = total
            self.progress_done = done
            self.progress_percent = int(done * 100 / total) if total else 0
            self.progress_message = str(message)

    def reset_progress(self) -> None:
        with self._lock:
            self.progress_percent = 0
            self.progress_message = ""
            self.progress_done = 0
            self.progress_total = 0

    def progress_payload(self) -> dict:
        with self._lock:
            return {
                "percent": self.progress_percent,
                "message": self.progress_message,
                "done": self.progress_done,
                "total": self.progress_total,
            }

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "phase": self.phase,
                "running": self.phase == "running",
                "log": list(self.log),
                "output": None if self.output is None else str(self.output),
                "error": self.error,
                "label": "构建数据库",
                "progress": self.progress_payload(),
            }

    def _append_log(self, text: str) -> None:
        for line in text.splitlines():
            line = line.rstrip()
            if line:
                self.log.append(line)

    def start(
        self,
        *,
        vanilla: Path,
        mod_root: Path | None,
        output: Path,
        server_state: MapServerState,
    ) -> None:
        with self._lock:
            if self.phase == "running":
                raise RuntimeError("已有构建任务正在运行")
            output = output.expanduser().resolve()
            if output.is_file():
                raise FileExistsError(f"输出文件已存在，拒绝覆盖：{output}")
            self.phase = "running"
            self.log = []
            self.output = output
            self.error = None
            self.reset_progress()

        def worker() -> None:
            try:
                self._run_build(vanilla, mod_root, output, server_state)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.phase = "error"
                    self.error = str(exc)
                    self._append_log(f"构建失败：{exc}")

        thread = threading.Thread(target=worker, name="map-editor-build", daemon=True)
        with self._lock:
            self._thread = thread
        thread.start()

    def _run_build(
        self,
        vanilla: Path,
        mod_root: Path | None,
        output: Path,
        server_state: MapServerState,
    ) -> None:
        register_import_paths()
        from build_db import build_map_db  # noqa: WPS433
        from editor_config import MapEditorConfig  # noqa: WPS433

        vanilla = vanilla.expanduser().resolve()
        if not vanilla.is_dir():
            raise FileNotFoundError(f"vanilla 目录不存在：{vanilla}")

        mod = mod_root.expanduser().resolve() if mod_root else vanilla
        if not mod.is_dir():
            raise FileNotFoundError(f"mod 目录不存在：{mod}")

        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        config = MapEditorConfig(vanilla=vanilla)
        self._append_log(f"vanilla: {vanilla}")
        self._append_log(f"mod_root: {mod}")
        self._append_log(f"output: {output}")

        def on_layer_progress(label_zh: str, done: int, total: int) -> None:
            self.report_progress(done, total, label_zh)

        def on_build_progress(done: int, total: int, message: str) -> None:
            self.report_build_progress(done, total, message)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            log = build_map_db(
                mod,
                output,
                config,
                fail_on_error=False,
                on_static_layer_progress=on_layer_progress,
                on_build_progress=on_build_progress,
            )
        self._append_log(buffer.getvalue())

        if log.warnings:
            self._append_log(f"警告 {len(log.warnings)} 条")
            for msg in log.warnings[:20]:
                self._append_log(f"  - {msg}")
            if len(log.warnings) > 20:
                self._append_log(f"  ... 另有 {len(log.warnings) - 20} 条")
        if log.errors:
            self._append_log(f"错误 {len(log.errors)} 条")
            for msg in log.errors[:20]:
                self._append_log(f"  - {msg}")
            if len(log.errors) > 20:
                self._append_log(f"  ... 另有 {len(log.errors) - 20} 条")

        if not output.is_file():
            raise FileNotFoundError(f"未生成文件：{output}")

        session = server_state.load(output)
        with self._lock:
            self.phase = "done"
            self._append_log(
                f"已加载 {session.db_path}（revision {session.revision}）"
            )
