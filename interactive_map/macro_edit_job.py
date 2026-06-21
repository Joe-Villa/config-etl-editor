"""Background job runner for slow country-level macro edits."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from interactive_map.map_session import MapSession
    from interactive_map.server_state import MapServerState

MacroJobPhase = Literal["idle", "running", "done", "error"]
ProgressFn = Callable[[int, str], None]

SLOW_COUNTRY_MACRO_PATHS: frozenset[str] = frozenset(
    {
        "country/expand-all-split",
        "country/annex-preserve",
        "country/annex-unincorporated",
        "country/change-tag",
        "country/incorporate-all",
        "country/release-country",
        "country/acquire-homelands",
        "country/homeland-remove-all",
        "country/homeland-clear-all",
        "country/homeland-clear-exclusive",
        "country/homeland-add-all",
        "country/homeland-fill",
        "country/convert-culture",
        "country/convert-religion",
    }
)

POP_COUNTRY_MACRO_PATHS: frozenset[str] = frozenset(
    {
        "country/convert-culture",
        "country/convert-religion",
    }
)

HOMELAND_COUNTRY_MACRO_PATHS: frozenset[str] = frozenset(
    {
        "country/homeland-remove-all",
        "country/homeland-clear-all",
        "country/homeland-clear-exclusive",
        "country/homeland-add-all",
        "country/homeland-fill",
    }
)

_MACRO_LABELS: dict[str, str] = {
    "country/expand-all-split": "扩展全部分属地区",
    "country/annex-preserve": "吞并（保留整合）",
    "country/annex-unincorporated": "吞并（新地区未整合）",
    "country/change-tag": "Change tag",
    "country/incorporate-all": "全部设为已整合",
    "country/release-country": "释放国家",
    "country/acquire-homelands": "获取全部文化本土",
    "country/homeland-remove-all": "批量删除文化本土",
    "country/homeland-clear-all": "移除全部文化本土（含分属）",
    "country/homeland-clear-exclusive": "移除全部文化本土（不含分属）",
    "country/homeland-add-all": "批量添加文化本土",
    "country/homeland-fill": "只给无本土地区添加文化本土",
    "country/convert-culture": "批量转化文化",
    "country/convert-religion": "批量转化宗教",
}


def macro_job_label(subpath: str) -> str:
    return _MACRO_LABELS.get(subpath, subpath)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_loop_progress(
    on_progress: ProgressFn | None,
    total: int,
    *,
    prefix: str = "",
) -> Callable[[str], None]:
    """Return a tick() helper that maps loop steps to 5–98%."""
    if on_progress is None or total <= 0:
        def noop(_message: str = "") -> None:
            return

        return noop

    label = prefix.strip()
    state = {"done": 0}
    on_progress(20, f"正在{label}（共 {total} 步）")

    def tick(message: str = "") -> None:
        state["done"] += 1
        done = state["done"]
        pct = min(90, 20 + int(done * 70 / total))
        detail = message or f"正在{label}（{done}/{total}）"
        on_progress(pct, detail)

    return tick


@dataclass
class MacroEditJob:
    phase: MacroJobPhase = "idle"
    request_id: str | None = None
    subpath: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result: dict | None = None
    revision: int | None = None
    error: str | None = None
    progress_percent: int = 0
    progress_message: str = ""
    progress_done: int = 0
    progress_total: int = 0
    client_view_layer: str | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def report_progress(
        self,
        percent: int,
        message: str,
        *,
        done: int | None = None,
        total: int | None = None,
    ) -> None:
        with self._lock:
            self.progress_percent = max(0, min(100, int(percent)))
            self.progress_message = str(message)
            if done is not None:
                self.progress_done = int(done)
            if total is not None:
                self.progress_total = int(total)

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
                "request_id": self.request_id,
                "subpath": self.subpath,
                "label": macro_job_label(self.subpath or ""),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "result": self.result,
                "revision": self.revision,
                "error": self.error,
                "progress": {
                    "percent": self.progress_percent,
                    "message": self.progress_message,
                    "done": self.progress_done,
                    "total": self.progress_total,
                },
            }

    def submit(
        self,
        *,
        request_id: str,
        subpath: str,
        runner: Callable[[], dict],
        client_view_layer: str | None = None,
    ) -> tuple[dict, int]:
        """Return (response_body, http_status)."""
        request_id = str(request_id).strip()
        subpath = str(subpath)
        with self._lock:
            if self.phase == "running":
                if self.request_id == request_id:
                    return self._running_response(), 202
                return self._rejected_response(request_id), 409
            if (
                self.phase == "done"
                and self.request_id == request_id
                and self.result is not None
            ):
                return self._done_response(), 200

            self.phase = "running"
            self.request_id = request_id
            self.subpath = subpath
            self.started_at = _utc_now()
            self.finished_at = None
            self.result = None
            self.revision = None
            self.error = None
            self.progress_percent = 0
            self.progress_message = "正在排队等待…"
            self.progress_done = 0
            self.progress_total = 0
            self.client_view_layer = str(client_view_layer).strip() if client_view_layer else None

        def worker() -> None:
            try:
                self.report_progress(1, "正在启动…")
                payload = runner()
                self.report_progress(99, "正在收尾…")
                with self._lock:
                    self.phase = "done"
                    self.finished_at = _utc_now()
                    self.result = dict(payload["result"])
                    self.revision = int(payload["revision"])
                    self.progress_percent = 100
                    self.progress_message = "正在更新界面…"
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.phase = "error"
                    self.finished_at = _utc_now()
                    self.error = str(exc)
                    self.progress_message = str(exc)

        thread = threading.Thread(
            target=worker,
            name=f"macro-edit-{subpath}",
            daemon=True,
        )
        with self._lock:
            self._thread = thread
        thread.start()
        return self._accepted_response(), 202

    def _accepted_response(self) -> dict:
        return {
            "status": "accepted",
            "phase": "running",
            "request_id": self.request_id,
            "subpath": self.subpath,
            "label": macro_job_label(self.subpath or ""),
            "started_at": self.started_at,
            "progress": self.progress_payload(),
        }

    def _running_response(self) -> dict:
        return {
            "status": "running",
            "phase": "running",
            "request_id": self.request_id,
            "subpath": self.subpath,
            "label": macro_job_label(self.subpath or ""),
            "started_at": self.started_at,
            "progress": self.progress_payload(),
        }

    def _done_response(self) -> dict:
        assert self.result is not None
        return {
            "status": "done",
            "phase": "done",
            "request_id": self.request_id,
            "subpath": self.subpath,
            "label": macro_job_label(self.subpath or ""),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "revision": self.revision,
            "progress": self.progress_payload(),
        }

    def _rejected_response(self, incoming_request_id: str) -> dict:
        return {
            "status": "rejected",
            "phase": "running",
            "reason": "another_job_running",
            "request_id": incoming_request_id,
            "active": {
                "request_id": self.request_id,
                "subpath": self.subpath,
                "label": macro_job_label(self.subpath or ""),
                "started_at": self.started_at,
            },
            "progress": self.progress_payload(),
        }


def run_slow_country_macro(
    server_state: MapServerState,
    subpath: str,
    payload: dict,
    *,
    progress_job: MacroEditJob | None = None,
) -> dict:
    """Execute a slow country macro under session lock; return result + revision."""
    from interactive_map.edit.atomic import atomic_edit
    from interactive_map.edit.country_homeland_macro import (
        acquire_all_homelands,
        batch_add_homeland,
        batch_fill_homeland,
        batch_remove_all_homelands,
        batch_remove_homeland,
        release_country,
    )
    from interactive_map.edit.country_pop_macro import (
        POP_INVALIDATE_LAYERS,
        batch_convert_culture,
        batch_convert_religion,
        normalize_religion_param,
    )
    from interactive_map.edit.state_geo import incorporate_all_states
    from interactive_map.edit.transfer import (
        annex_country_into,
        change_tag,
        expand_all_split_states,
    )

    def on_progress(percent: int, message: str) -> None:
        if progress_job is not None:
            progress_job.report_progress(percent, message)

    on_progress(3, "正在准备数据库事务…")
    with server_state.using_session() as session:
        with atomic_edit(session.conn):
            on_progress(8, f"正在{macro_job_label(subpath)}…")
            if subpath == "country/expand-all-split":
                result = expand_all_split_states(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/annex-preserve":
                result = annex_country_into(
                    session.conn,
                    acquirer_tag=str(payload.get("tag") or ""),
                    victim_tag=str(payload.get("victim_tag") or ""),
                    force_unincorporated=False,
                    on_progress=on_progress,
                )
            elif subpath == "country/annex-unincorporated":
                result = annex_country_into(
                    session.conn,
                    acquirer_tag=str(payload.get("tag") or ""),
                    victim_tag=str(payload.get("victim_tag") or ""),
                    force_unincorporated=True,
                    on_progress=on_progress,
                )
            elif subpath == "country/change-tag":
                result = change_tag(
                    session.conn,
                    old_tag=str(payload.get("tag") or ""),
                    new_tag=str(payload.get("new_tag") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/incorporate-all":
                result = incorporate_all_states(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/release-country":
                result = release_country(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    target_tag=str(payload.get("target_tag") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/acquire-homelands":
                result = acquire_all_homelands(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/homeland-remove-all":
                result = batch_remove_homeland(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    culture=str(payload.get("culture") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/homeland-clear-all":
                result = batch_remove_all_homelands(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    include_split=True,
                    on_progress=on_progress,
                )
            elif subpath == "country/homeland-clear-exclusive":
                result = batch_remove_all_homelands(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    include_split=False,
                    on_progress=on_progress,
                )
            elif subpath == "country/homeland-add-all":
                result = batch_add_homeland(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    culture=str(payload.get("culture") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/homeland-fill":
                result = batch_fill_homeland(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    culture=str(payload.get("culture") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/convert-culture":
                result = batch_convert_culture(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    from_culture=str(payload.get("from_culture") or ""),
                    to_culture=str(payload.get("to_culture") or ""),
                    on_progress=on_progress,
                )
            elif subpath == "country/convert-religion":
                result = batch_convert_religion(
                    session.conn,
                    tag=str(payload.get("tag") or ""),
                    from_religion=normalize_religion_param(
                        payload.get("from_religion")
                    ),
                    to_religion=normalize_religion_param(
                        payload.get("to_religion")
                    ),
                    on_progress=on_progress,
                )
            else:
                raise ValueError(f"unknown slow macro path: {subpath}")
            on_progress(91, "正在提交 SQLite 事务…")
            session.conn.commit()
            on_progress(93, "正在编码图层增量…")
            view_layer = str(payload.get("view_layer") or "").strip() or None
            if subpath in POP_COUNTRY_MACRO_PATHS:
                layers = tuple(result.get("invalidate_layers") or POP_INVALIDATE_LAYERS)
                revision = session.invalidate_layer_caches(*layers)
            elif subpath in HOMELAND_COUNTRY_MACRO_PATHS:
                revision = session.apply_homeland_edit()
            else:
                revision = session.apply_territory_edit(result, view_layer=view_layer)
    return {"result": result, "revision": revision}
