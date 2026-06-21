"""Pack all map layer PNGs into a zip archive (no border overlays on view layers)."""

from __future__ import annotations

import io
import zipfile

from interactive_map.export import _LAYER_FILES
from interactive_map.map_session import LAYER_NAMES, MapSession

# Main views first, then border-only layers (never composited onto view PNGs here).
EXPORT_LAYER_ORDER: tuple[str, ...] = LAYER_NAMES


def export_layers_zip(session: MapSession, *, run_id: str | None = None) -> bytes:
    """Return a zip of every view layer PNG plus standalone border PNGs."""
    meta = session.meta_json()
    prefix = run_id or str(meta.get("run_id") or "map")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for layer in EXPORT_LAYER_ORDER:
            png = session.layer_png(layer)
            filename = _LAYER_FILES.get(layer, f"{layer}.png")
            archive.writestr(f"{prefix}_{filename}", png)
    return buf.getvalue()
