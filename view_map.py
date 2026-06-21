#!/usr/bin/env python3
"""Launch map editor interactive viewer (SQL-driven API server + web launcher)."""

from __future__ import annotations

import argparse
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import runtime_deps  # noqa: E402

runtime_deps.register()

from interactive_map.api_server import (  # noqa: E402
    create_map_server,
    run_until_shutdown,
    start_map_server_background,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="地图编辑器 · 交互地图")
    parser.add_argument(
        "database",
        type=Path,
        nargs="?",
        default=None,
        help="可选：启动时预加载的 map_editor.sqlite 路径",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="仅导出静态 web/ 快照（CI/离线），不启动服务",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="使用 Tkinter 启动器（旧方式）",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="不打开浏览器/GUI，仅运行 API 服务（需已指定 database）",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="不自动打开浏览器（默认会在启动服务后打开）",
    )
    args = parser.parse_args()

    if args.gui and args.no_gui:
        raise SystemExit("不能同时使用 --gui 与 --no-gui")

    if args.export_only:
        if args.database is None:
            raise SystemExit("export-only 需要指定 database 路径")
        if not args.database.is_file():
            raise SystemExit(f"找不到数据库：{args.database}")
        export_py = ROOT / "interactive_map" / "export.py"
        subprocess.run(
            [sys.executable, str(export_py), str(args.database)],
            check=True,
        )
        return

    db_path = args.database.resolve() if args.database else None
    if db_path is not None and not db_path.is_file():
        raise SystemExit(f"找不到数据库：{db_path}")

    viewer_url = f"http://{args.host}:{args.port}/viewer/index.html"

    if args.no_gui:
        if db_path is None:
            raise SystemExit("未加载数据库且使用了 --no-gui")
        server, server_state = create_map_server(
            host=args.host,
            port=args.port,
            db_path=db_path,
        )
        serve_thread = None
    else:
        server, server_state, serve_thread = start_map_server_background(
            host=args.host,
            port=args.port,
            db_path=db_path,
        )

    print(f"API 服务: {viewer_url}")
    if db_path is None:
        print("尚未加载数据库，请在浏览器中加载或构建 map_editor.sqlite")

    if args.no_gui:
        print("服务运行中，按 Ctrl+C 停止。")
        run_until_shutdown(server, server_state)
        return

    if args.gui:
        try:
            from launcher_gui import run_launcher_gui  # noqa: WPS433

            run_launcher_gui(
                server_state=server_state,
                host=args.host,
                port=args.port,
            )
        finally:
            server.shutdown()
            if serve_thread is not None:
                serve_thread.join(timeout=5)
            server.server_close()
            server_state.close()
        return

    if not args.no_browser:
        webbrowser.open(viewer_url)

    print("服务运行中，按 Ctrl+C 停止。")
    run_until_shutdown(server, server_state, serve_thread=serve_thread)


if __name__ == "__main__":
    main()
