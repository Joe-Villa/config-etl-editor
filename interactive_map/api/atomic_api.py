"""HTTP adapters for atomic control-layer operations (/api/atomic/*)."""

from __future__ import annotations

from http import HTTPStatus
from urllib.parse import parse_qs

from interactive_map.control.view_service import ViewService
from interactive_map.incremental_layers import DATA_DRIVEN_VIEW_LAYERS, DYNAMIC_VIEW_LAYERS
from interactive_map.macro_edit_job import HOMELAND_COUNTRY_MACRO_PATHS, POP_COUNTRY_MACRO_PATHS
from interactive_map.map_session import MapSession


def view_layer_from_payload(payload: dict | None) -> str | None:
    if not payload:
        return None
    layer = str(payload.get("view_layer") or "").strip()
    return layer or None


def handle_atomic_get(
    handler,
    subpath: str,
    query: str,
    session: MapSession,
) -> None:
    if subpath == "map-bootstrap.json":
        payload = ViewService.map_bootstrap(session)
        handler._send_json(payload, revision=session.revision)
        return

    if subpath == "country-panel.json":
        params = parse_qs(query)
        tag = (params.get("tag") or [None])[0]
        if not tag:
            handler._send_error(HTTPStatus.BAD_REQUEST, "需要 tag 参数")
            return
        try:
            payload = ViewService.country_panel(session.conn, tag)
        except ValueError as exc:
            handler._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        handler._send_json(payload, revision=session.revision)
        return

    if subpath == "layer-data.json":
        params = parse_qs(query)
        layer = (params.get("layer") or [None])[0]
        if not layer or layer not in DATA_DRIVEN_VIEW_LAYERS:
            handler._send_error(HTTPStatus.BAD_REQUEST, "需要有效的 layer 参数")
            return
        try:
            payload = ViewService.lazy_layer_json(session, layer)
        except KeyError:
            handler._send_error(HTTPStatus.BAD_REQUEST, f"未知图层：{layer}")
            return
        handler._send_json({"layer": layer, "data": payload}, revision=session.revision)
        return

    handler._send_error(HTTPStatus.NOT_FOUND, f"unknown atomic path: {subpath}")


def handle_atomic_post(
    handler,
    subpath: str,
    payload: dict,
    session: MapSession,
) -> None:
    if subpath == "refresh-layer.json":
        layer = str(payload.get("layer") or "").strip()
        if not layer or layer not in DYNAMIC_VIEW_LAYERS:
            handler._send_error(
                HTTPStatus.BAD_REQUEST,
                "需要有效的动态视图 layer 参数",
            )
            return
        try:
            body = ViewService.refresh_view_layer(session, layer)
        except ValueError as exc:
            handler._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        handler._send_json(body, revision=session.revision)
        return

    handler._send_error(HTTPStatus.NOT_FOUND, f"unknown atomic path: {subpath}")


def attach_view_patch(
    session: MapSession,
    body: dict,
    *,
    mode: str,
    view_layer: str | None = None,
) -> dict:
    """Merge control-layer view patch into an edit response (single UI update)."""
    revision = int(body.get("revision", session.revision))
    if mode == "territory":
        patch = ViewService.territory_view_patch(
            session,
            revision,
            view_layer=view_layer,
        )
    elif mode == "homeland":
        patch = ViewService.homeland_view_patch(
            session,
            revision,
            view_layer=view_layer,
        )
    elif mode == "claim":
        patch = ViewService.homeland_view_patch(
            session,
            revision,
            view_layer=view_layer,
        )
    elif mode == "scope_data":
        patch = ViewService.scope_data_view_patch(
            session,
            revision,
            view_layer=view_layer,
        )
    else:
        patch = {"revision": revision, "view_layer": view_layer}
    body = dict(body)
    body["view_patch"] = patch
    return body


def macro_job_view_mode(subpath: str | None) -> str:
    if subpath in HOMELAND_COUNTRY_MACRO_PATHS:
        return "homeland"
    if subpath in POP_COUNTRY_MACRO_PATHS:
        return "scope_data"
    return "territory"


def enrich_macro_job_snapshot(
    session: MapSession,
    snap: dict,
    *,
    view_layer: str | None = None,
) -> dict:
    """Attach view_patch to completed macro job snapshots (one frontend update)."""
    if snap.get("phase") != "done" or snap.get("revision") is None or snap.get("result") is None:
        return snap
    mode = macro_job_view_mode(snap.get("subpath"))
    merged = attach_view_patch(
        session,
        {**snap["result"], "revision": int(snap["revision"])},
        mode=mode,
        view_layer=view_layer,
    )
    out = dict(snap)
    out["result"] = merged
    out["view_patch"] = merged["view_patch"]
    return out
