#!/usr/bin/env python3
"""HTTP server: viewer static files + /api/* from MapSession (SQL-driven)."""

from __future__ import annotations

import argparse
import json
import mimetypes
import sqlite3
import sys
import threading
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlparse

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from app_paths import bootstrap_impl_root, package_root, viewer_root

ROOT = package_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = bootstrap_impl_root()
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from interactive_map.api.atomic_api import (  # noqa: E402
    attach_view_patch,
    enrich_macro_job_snapshot,
    handle_atomic_get,
    handle_atomic_post,
    view_layer_from_payload,
)
from interactive_map.edit.buildings import (  # noqa: E402
    BUILDING_LEVEL_ERROR,
    DEFAULT_OWNERSHIP_TYPE,
    add_building,
    delete_building,
    load_building_options,
    parse_building_level,
    update_building,
)
from interactive_map.edit.pops import (  # noqa: E402
    POP_SIZE_ERROR,
    add_pop,
    delete_pop,
    load_pop_options,
    normalize_is_slaves,
    parse_pop_size,
    update_pop,
)
from interactive_map.edit.state_geo import (  # noqa: E402
    change_claim,
    change_homeland,
    change_state_type,
    load_state_geo_options,
)
from interactive_map.edit.country_homeland_macro import (  # noqa: E402
    load_acquire_homelands_preview,
    load_release_country_preview,
)
from interactive_map.edit.transfer import (  # noqa: E402
    annex_country,
    load_country_macro_preview,
    load_country_macro_section,
    load_transfer_options,
    set_owner,
    expand_scope_to_full_state,
    load_state_expansion_preview,
    transfer_province,
    transfer_scope_state,
    transfer_state,
)
from interactive_map.db_snapshot import create_snapshot, list_snapshots  # noqa: E402
from interactive_map.edit.log import export_edit_log  # noqa: E402
from interactive_map.export_history import (  # noqa: E402
    EXPORT_CATEGORIES,
    export_history_bundle,
    export_history_files,
    export_history_zip,
)
from interactive_map.export_layers import export_layers_zip  # noqa: E402
from interactive_map.macro_edit_job import (  # noqa: E402
    SLOW_COUNTRY_MACRO_PATHS,
    run_slow_country_macro,
)
from bootstrap.build_job import launcher_defaults  # noqa: E402
from runtime.server_state import MapServerState  # noqa: E402
from interactive_map.map_session import JSON_DOCUMENTS, LAYER_NAMES, MapSession  # noqa: E402
from interactive_map.state_detail import load_state_detail_json  # noqa: E402

VIEWER_ROOT = viewer_root()

_LAYER_ALIASES = {
    "ownership.png": "ownership",
    "terrain.png": "terrain",
    "incorporation.png": "incorporation",
    "country_type.png": "country_type",
    "homeland.png": "homeland",
    "claims.png": "claims",
    "foreign_investment.png": "foreign_investment",
    "building_level.png": "building_level",
    "slavery.png": "slavery",
    "pop_total.png": "pop_total",
    "pop_culture.png": "pop_culture",
    "pop_religion.png": "pop_religion",
    "hubs.png": "hubs",
    "strategic_region.png": "strategic_region",
    "raw.png": "raw",
    "border_province.png": "border_province",
    "border_state.png": "border_state",
    "border_country.png": "border_country",
}


class MapEditorHandler(BaseHTTPRequestHandler):
    server_state: MapServerState

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        if str(args[1]) != "200":
            super().log_message(format, *args)

    def _require_session(self) -> MapSession:
        session = self.server_state.session
        if session is None:
            self._send_error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "尚未加载数据库，请在页面中加载或构建 map_editor.sqlite",
            )
            raise RuntimeError("no database loaded")
        return session

    @contextmanager
    def _open_session(self) -> Iterator[MapSession]:
        try:
            with self.server_state.using_session() as session:
                yield session
        except RuntimeError as exc:
            if str(exc) == "no database loaded":
                self._send_error(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "尚未加载数据库，请在页面中加载或构建 map_editor.sqlite",
                )
            raise

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            try:
                self._handle_api(path[len("/api/") :], parsed.query)
            except RuntimeError:
                pass
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            except sqlite3.Error as exc:
                self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        if path in ("", "/"):
            self._redirect("/viewer/index.html")
            return
        if path.startswith("/viewer/"):
            self._serve_file(VIEWER_ROOT, path[len("/viewer/") :])
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/refresh":
                with self._open_session() as session:
                    revision = session.refresh()
                self._send_json({"revision": revision})
                return
            if parsed.path == "/api/load-database":
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b"{}"
                payload = json.loads(body.decode("utf-8"))
                raw_path = payload.get("path")
                if not raw_path:
                    self._send_error(HTTPStatus.BAD_REQUEST, "需要 path 字段")
                    return
                session = self.server_state.load(Path(str(raw_path)))
                self._send_json(
                    {
                        "database": str(session.db_path),
                        "revision": session.revision,
                    }
                )
                return
            if parsed.path == "/api/build-database":
                payload = self._read_json_body()
                from interactive_map.build_job import launcher_defaults

                defaults = launcher_defaults()
                vanilla_raw = payload.get("vanilla") or defaults.get("vanilla")
                if not vanilla_raw:
                    self._send_error(
                        HTTPStatus.BAD_REQUEST, "需要 vanilla 路径"
                    )
                    return
                mod_raw = payload.get("mod_root")
                mod_root = Path(str(mod_raw)) if mod_raw else None
                output_raw = payload.get("output") or defaults.get("output")
                if not output_raw:
                    self._send_error(
                        HTTPStatus.BAD_REQUEST, "需要 output 路径"
                    )
                    return
                output = Path(str(output_raw)).expanduser().resolve()
                if output.is_file():
                    self._send_error(
                        HTTPStatus.CONFLICT,
                        f"输出文件已存在，拒绝覆盖：{output}",
                    )
                    return
                try:
                    self.server_state.build_job.start(
                        vanilla=Path(str(vanilla_raw)),
                        mod_root=mod_root,
                        output=output,
                        server_state=self.server_state,
                    )
                except RuntimeError as exc:
                    self._send_error(HTTPStatus.CONFLICT, str(exc))
                    return
                except FileExistsError as exc:
                    self._send_error(HTTPStatus.CONFLICT, str(exc))
                    return
                except FileNotFoundError as exc:
                    self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                    return
                self._send_json(
                    {
                        "started": True,
                        "output": str(output.expanduser().resolve()),
                    }
                )
                return
            if parsed.path == "/api/db-snapshot/save":
                payload = self._read_json_body()
                label = str(payload.get("label") or "").strip()
                with self._open_session() as session:
                    entry = create_snapshot(
                        session.db_path,
                        label=label,
                        conn=session.conn,
                    )
                self._send_json({"snapshot": entry})
                return
            if parsed.path == "/api/db-snapshot/restore":
                payload = self._read_json_body()
                snapshot_id = str(payload.get("id") or "").strip()
                if not snapshot_id:
                    self._send_error(HTTPStatus.BAD_REQUEST, "需要 id 字段")
                    return
                try:
                    result = self.server_state.restore_db_snapshot(snapshot_id)
                except FileNotFoundError as exc:
                    self._send_error(HTTPStatus.NOT_FOUND, str(exc))
                    return
                self._send_json(result, revision=result["revision"])
                return
        except RuntimeError:
            return
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except FileNotFoundError as exc:
            self._send_error(HTTPStatus.NOT_FOUND, str(exc))
            return
        if parsed.path.startswith("/api/atomic/"):
            try:
                with self._open_session() as session:
                    handle_atomic_post(
                        self,
                        parsed.path[len("/api/atomic/") :],
                        self._read_json_body(),
                        session,
                    )
            except RuntimeError:
                pass
            return
        try:
            if parsed.path.startswith("/api/edit/"):
                self._handle_edit_post(parsed.path[len("/api/edit/") :])
                return
        except RuntimeError:
            return
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except sqlite3.IntegrityError as exc:
            text = str(exc)
            if "st_bld_own" in text or "level" in text.lower():
                message = BUILDING_LEVEL_ERROR
            elif "st_pop" in text or "size" in text.lower():
                message = POP_SIZE_ERROR
            else:
                message = text
            self._send_error(HTTPStatus.BAD_REQUEST, message)
            return
        self._send_error(HTTPStatus.NOT_FOUND, "not found")

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body 必须是 object")
        return payload

    def _commit_territory_edit(
        self,
        session: MapSession,
        result: dict,
        *,
        view_layer: str | None = None,
    ) -> int:
        session.conn.commit()
        return session.apply_territory_edit(result, view_layer=view_layer)

    def _commit_edit(
        self,
        session: MapSession,
        result: dict | None = None,
        *,
        mode: str = "full",
        view_layer: str | None = None,
    ) -> int:
        session.conn.commit()
        if mode == "territory" and result is not None:
            return session.apply_territory_edit(result, view_layer=view_layer)
        if mode == "homeland":
            state = str((result or {}).get("state") or "")
            return session.apply_homeland_edit(state)
        if mode == "claim":
            state = str((result or {}).get("state") or "")
            return session.apply_claim_edit(state)
        if mode == "metadata":
            return session.bump_revision()
        if mode == "scope_data":
            layers = list(result.get("invalidate_layers") or ()) if result else ()
            if layers:
                return session.invalidate_layer_caches(*layers)
            return session.bump_revision()
        return session.refresh()

    def _send_edit_result(
        self,
        session: MapSession,
        result: dict,
        revision: int,
        *,
        mode: str,
        view_layer: str | None = None,
    ) -> None:
        self._send_json(
            attach_view_patch(
                session,
                {**result, "revision": revision},
                mode=mode,
                view_layer=view_layer,
            ),
            revision=revision,
        )

    def _handle_slow_country_macro(
        self, session: MapSession, subpath: str, payload: dict
    ) -> None:
        request_id = str(payload.get("request_id") or "").strip()
        if not request_id:
            self._send_error(
                HTTPStatus.BAD_REQUEST,
                "耗时国家宏操作需要 request_id 以防重复提交",
            )
            return

        def runner() -> dict:
            return run_slow_country_macro(
                self.server_state,
                subpath,
                payload,
                progress_job=self.server_state.macro_edit_job,
            )

        body, code = self.server_state.macro_edit_job.submit(
            request_id=request_id,
            subpath=subpath,
            runner=runner,
            client_view_layer=view_layer_from_payload(payload),
        )
        if code == 200 and body.get("phase") == "done":
            body = enrich_macro_job_snapshot(
                session,
                body,
                view_layer=self.server_state.macro_edit_job.client_view_layer,
            )
        revision = body.get("revision")
        self._send_json(body, revision=revision, status=code)

    def _handle_edit_post(self, subpath: str) -> None:
        from interactive_map.edit.atomic import atomic_edit

        payload = self._read_json_body()
        view_layer = view_layer_from_payload(payload)

        if subpath in SLOW_COUNTRY_MACRO_PATHS:
            try:
                with self._open_session() as session:
                    self._handle_slow_country_macro(session, subpath, payload)
            except RuntimeError:
                pass
            return

        try:
            with self._open_session() as session:
                with atomic_edit(session.conn):
                    if subpath == "transfer/province":
                        result = transfer_province(
                            session.conn,
                            province_hex=str(payload.get("province") or ""),
                            new_tag=str(payload.get("new_tag") or ""),
                            origin_tag=payload.get("origin_tag"),
                            state_type=payload.get("state_type"),
                        )
                        revision = self._commit_edit(session, result, mode="territory", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="territory", view_layer=view_layer)
                        return
                    if subpath == "transfer/state":
                        result = transfer_state(
                            session.conn,
                            state=str(payload.get("state") or ""),
                            origin_tag=str(payload.get("origin_tag") or ""),
                            new_tag=str(payload.get("new_tag") or ""),
                            state_type=payload.get("state_type"),
                        )
                        revision = self._commit_edit(session, result, mode="territory", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="territory", view_layer=view_layer)
                        return
                    if subpath == "transfer/scope":
                        result = transfer_scope_state(
                            session.conn,
                            tag=str(payload.get("tag") or ""),
                            state=str(payload.get("state") or ""),
                            new_tag=str(payload.get("new_tag") or ""),
                            state_type=payload.get("state_type"),
                        )
                        revision = self._commit_edit(session, result, mode="territory", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="territory", view_layer=view_layer)
                        return
                    if subpath == "transfer/expand":
                        result = expand_scope_to_full_state(
                            session.conn,
                            tag=str(payload.get("tag") or ""),
                            state=str(payload.get("state") or ""),
                        )
                        revision = self._commit_edit(session, result, mode="territory", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="territory", view_layer=view_layer)
                        return
                    if subpath == "transfer/annex":
                        result = annex_country(
                            session.conn,
                            origin_tag=str(payload.get("origin_tag") or ""),
                            new_tag=str(payload.get("new_tag") or ""),
                            state_type=str(payload.get("state_type") or "unincorporated"),
                        )
                        revision = self._commit_edit(session, result, mode="territory", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="territory", view_layer=view_layer)
                        return
                    if subpath == "transfer/set-owner":
                        result = set_owner(
                            session.conn,
                            province_hex=str(payload.get("province") or ""),
                            new_tag=str(payload.get("new_tag") or ""),
                            origin_tag=payload.get("origin_tag"),
                        )
                        revision = self._commit_edit(session, result, mode="territory", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="territory", view_layer=view_layer)
                        return
                    if subpath == "state/type":
                        result = change_state_type(
                            session.conn,
                            tag=str(payload.get("tag") or ""),
                            state=str(payload.get("state") or ""),
                            state_type=str(payload.get("state_type") or ""),
                        )
                        revision = self._commit_edit(session, result, mode="territory", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="territory", view_layer=view_layer)
                        return
                    if subpath == "state/homeland":
                        result = change_homeland(
                            session.conn,
                            state=str(payload.get("state") or ""),
                            culture=str(payload.get("culture") or ""),
                            action=str(payload.get("action") or ""),
                        )
                        revision = self._commit_edit(session, result, mode="homeland", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="homeland", view_layer=view_layer)
                        return
                    if subpath == "state/claim":
                        result = change_claim(
                            session.conn,
                            state=str(payload.get("state") or ""),
                            claim_tag=str(payload.get("claim_tag") or ""),
                            action=str(payload.get("action") or ""),
                        )
                        revision = self._commit_edit(session, result, mode="claim", view_layer=view_layer)
                        self._send_edit_result(session, result, revision, mode="claim", view_layer=view_layer)
                        return

                    tag = str(payload.get("tag") or "")
                    state = str(payload.get("state") or "")
                    if not tag or not state:
                        raise ValueError("需要 tag 与 state（scope state）")

                    if subpath == "building/add":
                        result = add_building(
                            session.conn,
                            tag=tag,
                            state=state,
                            building=str(payload.get("building") or ""),
                            pms=payload.get("pms"),
                            level=parse_building_level(payload.get("level", 1)),
                            ownership_type=str(
                                payload.get("ownership_type") or DEFAULT_OWNERSHIP_TYPE
                            ),
                            owner_tag=str(payload.get("owner_tag") or ""),
                            owner_state=str(payload.get("owner_state") or ""),
                        )
                    elif subpath == "building/delete":
                        result = delete_building(
                            session.conn,
                            tag=tag,
                            state=state,
                            bld_id=int(payload["bld_id"]),
                        )
                    elif subpath == "building/update":
                        result = update_building(
                            session.conn,
                            tag=tag,
                            state=state,
                            bld_id=int(payload["bld_id"]),
                            pms=payload.get("pms"),
                            level=parse_building_level(payload.get("level", 1)),
                            ownership_type=str(
                                payload.get("ownership_type") or DEFAULT_OWNERSHIP_TYPE
                            ),
                            owner_tag=str(payload.get("owner_tag") or ""),
                            owner_state=str(payload.get("owner_state") or ""),
                            sync_pm_same_key=bool(payload.get("sync_pm_same_key", True)),
                        )
                    elif subpath == "pop/add":
                        result = add_pop(
                            session.conn,
                            tag=tag,
                            state=state,
                            culture=str(payload.get("culture") or ""),
                            religion=payload.get("religion"),
                            is_slaves=normalize_is_slaves(payload.get("is_slaves", False)),
                            size=parse_pop_size(payload.get("size", 1000)),
                        )
                    elif subpath == "pop/delete":
                        result = delete_pop(
                            session.conn,
                            tag=tag,
                            state=state,
                            pop_id=int(payload["pop_id"]),
                        )
                    elif subpath == "pop/update":
                        result = update_pop(
                            session.conn,
                            tag=tag,
                            state=state,
                            pop_id=int(payload["pop_id"]),
                            culture=str(payload.get("culture") or ""),
                            religion=payload.get("religion"),
                            is_slaves=normalize_is_slaves(payload.get("is_slaves", False)),
                            size=parse_pop_size(payload.get("size", 1000)),
                        )
                    else:
                        self._send_error(HTTPStatus.NOT_FOUND, f"unknown edit path: {subpath}")
                        return
                    if subpath.startswith("building/"):
                        result["invalidate_layers"] = (
                            "foreign_investment",
                            "building_level",
                        )
                    else:
                        result["invalidate_layers"] = (
                            "slavery",
                            "pop_total",
                            "pop_culture",
                            "pop_religion",
                        )
                    revision = self._commit_edit(
                        session,
                        result,
                        mode="scope_data",
                        view_layer=view_layer,
                    )
                self._send_edit_result(
                    session,
                    result,
                    revision,
                    mode="scope_data",
                    view_layer=view_layer,
                )
        except RuntimeError:
            return

    def _handle_api(self, subpath: str, query: str) -> None:
        if subpath == "status.json":
            self._send_json(self.server_state.status_json())
            return

        if subpath == "edit/macro-job.json":
            # Progress polling must not take the session lock — the macro worker
            # holds it for the entire operation, which would freeze the bar at ~3%.
            snap = self.server_state.macro_edit_job.snapshot()
            if snap.get("phase") == "done" and snap.get("revision") is not None:
                try:
                    with self._open_session() as session:
                        snap = enrich_macro_job_snapshot(
                            session,
                            snap,
                            view_layer=self.server_state.macro_edit_job.client_view_layer,
                        )
                except RuntimeError:
                    pass
            self._send_json(snap)
            return

        if subpath.startswith("atomic/"):
            try:
                with self._open_session() as session:
                    handle_atomic_get(
                        self,
                        subpath[len("atomic/") :],
                        query,
                        session,
                    )
            except RuntimeError:
                pass
            return

        try:
            with self._open_session() as session:
                self._handle_api_with_session(session, subpath, query)
        except RuntimeError:
            return

    def _handle_api_with_session(
        self, session: MapSession, subpath: str, query: str
    ) -> None:
        if subpath == "provinces.png":
            self._send_bytes(
                session.provinces_png(),
                "image/png",
                revision=session.revision,
            )
            return

        if subpath.startswith("layer/"):
            layer_file = subpath[len("layer/") :]
            layer_name = _LAYER_ALIASES.get(layer_file)
            if layer_name is None:
                self._send_error(HTTPStatus.NOT_FOUND, f"unknown layer: {layer_file}")
                return
            self._send_bytes(
                session.layer_png(layer_name),
                "image/png",
                revision=session.revision,
            )
            return

        if subpath == "state-detail.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            state = (params.get("state") or [None])[0]
            if not tag or not state:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 与 state 参数")
                return
            payload = load_state_detail_json(session.conn, tag, state)
            if payload is None:
                self._send_error(HTTPStatus.NOT_FOUND, "未找到 tag+state")
                return
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/building-options.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            state = (params.get("state") or [None])[0]
            building = (params.get("building") or [None])[0]
            if not tag or not state:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 与 state 参数")
                return
            payload = load_building_options(
                session.conn, tag, state, building=building or None
            )
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/pop-options.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            state = (params.get("state") or [None])[0]
            if not tag or not state:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 与 state 参数")
                return
            payload = load_pop_options(session.conn, tag, state)
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/transfer-options.json":
            payload = load_transfer_options(session.conn)
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/state-expansion.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            state = (params.get("state") or [None])[0]
            if not tag or not state:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 与 state 参数")
                return
            payload = load_state_expansion_preview(session.conn, tag, state)
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/state-geo-options.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            state = (params.get("state") or [None])[0]
            if not tag or not state:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 与 state 参数")
                return
            payload = load_state_geo_options(session.conn, tag, state)
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/release-country-preview.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            target_tag = (params.get("target_tag") or [None])[0]
            if not tag:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 参数")
                return
            payload = load_release_country_preview(
                session.conn,
                tag,
                target_tag=target_tag,
            )
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/acquire-homelands-preview.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            if not tag:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 参数")
                return
            payload = load_acquire_homelands_preview(session.conn, tag)
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/country-macro.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            if not tag:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 参数")
                return
            try:
                payload = load_country_macro_preview(session.conn, tag)
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "edit/country-macro-section.json":
            params = parse_qs(query)
            tag = (params.get("tag") or [None])[0]
            section = (params.get("section") or [None])[0]
            if not tag or not section:
                self._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 与 section 参数")
                return
            try:
                payload = load_country_macro_section(session.conn, tag, section)
            except ValueError as exc:
                self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            self._send_json(payload, revision=session.revision)
            return

        if subpath == "db-snapshots.json":
            self._send_json({"snapshots": list_snapshots(session.db_path)})
            return

        if subpath == "export/history.zip":
            payload = export_history_zip(session.conn)
            self._send_bytes(
                payload,
                "application/zip",
                revision=session.revision,
                extra_headers={
                    "Content-Disposition": 'attachment; filename="history.zip"',
                    "Cache-Control": "no-store",
                },
            )
            return

        if subpath == "export/layers.zip":
            meta = session.meta_json()
            run_id = str(meta.get("run_id") or "map")
            payload = export_layers_zip(session, run_id=run_id)
            self._send_bytes(
                payload,
                "application/zip",
                revision=session.revision,
                extra_headers={
                    "Content-Disposition": f'attachment; filename="{run_id}_layers.zip"',
                    "Cache-Control": "no-store",
                },
            )
            return

        if subpath == "export/edit-log.json":
            payload = export_edit_log(session.conn)
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self._send_bytes(
                body,
                "application/json; charset=utf-8",
                revision=session.revision,
                extra_headers={
                    "Content-Disposition": 'attachment; filename="edit-log.json"',
                    "Cache-Control": "no-store",
                },
            )
            return

        if subpath == "export/history.json":
            file_map = export_history_files(session.conn)
            self._send_json(
                {
                    "categories": list(EXPORT_CATEGORIES),
                    "files": {
                        category: sorted(files.keys())
                        for category, files in file_map.items()
                    },
                    **export_history_bundle(session.conn),
                },
                revision=session.revision,
            )
            return

        if subpath.endswith(".json"):
            doc_name = subpath[: -len(".json")]
            if doc_name not in JSON_DOCUMENTS:
                self._send_error(HTTPStatus.NOT_FOUND, f"unknown document: {doc_name}")
                return
            if doc_name == "meta":
                payload = session.meta_json()
            else:
                payload = session.json_document(doc_name)
            self._send_json(payload, revision=session.revision)
            return

        self._send_error(HTTPStatus.NOT_FOUND, f"unknown api path: {subpath}")

    def _serve_file(self, base: Path, rel: str) -> None:
        rel_path = Path(rel)
        if rel_path.is_absolute() or ".." in rel_path.parts:
            self._send_error(HTTPStatus.FORBIDDEN, "invalid path")
            return
        file_path = (base / rel_path).resolve()
        if not str(file_path).startswith(str(base.resolve())):
            self._send_error(HTTPStatus.FORBIDDEN, "invalid path")
            return
        if not file_path.is_file():
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        content = file_path.read_bytes()
        mime, _ = mimetypes.guess_type(str(file_path))
        self._send_bytes(content, mime or "application/octet-stream")

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.end_headers()

    def _send_json(
        self,
        payload: object,
        *,
        revision: int | None = None,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        extra: dict[str, str] = {"Cache-Control": "no-store"}
        if revision is not None:
            extra["X-Map-Revision"] = str(revision)
        self._write_body(body, "application/json; charset=utf-8", extra, status=status)

    def _send_bytes(
        self,
        body: bytes,
        content_type: str,
        *,
        revision: int | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        headers: dict[str, str] = dict(extra_headers or {})
        if revision is not None:
            headers["X-Map-Revision"] = str(revision)
        if "Cache-Control" not in headers:
            headers["Cache-Control"] = "no-store"
        self._write_body(body, content_type, headers or None)

    def _write_body(
        self,
        body: bytes,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        self.send_response(status)
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_error(self, code: HTTPStatus, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_map_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Path | None = None,
    server_state: MapServerState | None = None,
) -> tuple[ThreadingHTTPServer, MapServerState]:
    state = server_state or MapServerState()
    if db_path is not None:
        state.load(db_path)
    handler = type(
        "BoundMapEditorHandler",
        (MapEditorHandler,),
        {"server_state": state},
    )
    return ThreadingHTTPServer((host, port), handler), state


def start_map_server_background(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Path | None = None,
    server_state: MapServerState | None = None,
    daemon: bool = False,
) -> tuple[ThreadingHTTPServer, MapServerState, threading.Thread]:
    server, state = create_map_server(
        host=host,
        port=port,
        db_path=db_path,
        server_state=server_state,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="map-editor-http",
        daemon=daemon,
    )
    thread.start()
    return server, state, thread


def run_until_shutdown(
    server: ThreadingHTTPServer,
    server_state: MapServerState,
    *,
    serve_thread: threading.Thread | None = None,
) -> None:
    """Block until Ctrl+C or server.shutdown(); then release resources."""
    try:
        if serve_thread is not None:
            serve_thread.join()
        else:
            server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.shutdown()
        server.server_close()
        server_state.close()


def serve_map(
    db_path: Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    server, state = create_map_server(host=host, port=port, db_path=db_path)
    loaded = state.session
    print(f"数据库: {loaded.db_path if loaded else '（未加载）'}")
    if loaded is not None:
        print(f"revision: {loaded.revision}")
    print(f"在浏览器打开: http://{host}:{port}/viewer/index.html")
    print("API 前缀: /api/  （数据与图层均来自 SQL，运行时生成）")
    print("编辑数据库后 POST /api/refresh 或重启服务")
    print("服务运行中，按 Ctrl+C 停止。")
    run_until_shutdown(server, state)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="启动地图编辑器 API 服务（运行时读 sqlite，不依赖 web/ 导出）"
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="map_editor.sqlite 路径（省略则启动时不加载）",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    db_path = args.database.resolve() if args.database else None
    if db_path is not None and not db_path.is_file():
        raise SystemExit(f"找不到数据库：{db_path}")

    serve_map(db_path, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
