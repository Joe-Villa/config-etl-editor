#!/usr/bin/env python3
"""Serve map editor viewer via SQL-driven API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.api_server import serve_map  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="启动地图编辑器 API 服务")
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
