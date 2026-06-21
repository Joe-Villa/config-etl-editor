#!/usr/bin/env python3
"""Launch map editor web UI from an existing sqlite database (viewer-only build entry)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from app_paths import package_root
import runtime_deps

ROOT = package_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

runtime_deps.register()

from interactive_map.api_server import (  # noqa: E402
    create_map_server,
    run_until_shutdown,
    start_map_server_background,
)


def _run_viewer_gui(**kwargs: object) -> None:
    try:
        from launcher_viewer_gui import run_viewer_launcher_gui
    except ModuleNotFoundError as exc:
        if exc.name in ("tkinter", "_tkinter"):
            raise SystemExit(
                "当前环境没有 tkinter（Windows 便携版不含 GUI）。\n"
                "请使用 map_editor.exe 启动，或运行：\n"
                "  python viewer_launcher.py --no-gui 你的数据库.sqlite"
            ) from exc
        raise
    run_viewer_launcher_gui(**kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description="地图编辑器 · 打开数据库并启动网页编辑器")
    parser.add_argument(
        "database",
        type=Path,
        nargs="?",
        default=None,
        help="可选：启动时预加载的 .sqlite 路径",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="不显示启动器 GUI（需已指定 database）",
    )
    args = parser.parse_args()

    db_path = args.database.resolve() if args.database else None
    if db_path is not None and not db_path.is_file():
        raise SystemExit(f"找不到数据库：{db_path}")

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

    print(f"API 服务: http://{args.host}:{args.port}/viewer/index.html")
    if db_path is None:
        print("尚未加载数据库，请在启动器中选择 .sqlite 文件")

    if args.no_gui and server_state.session is not None:
        import threading
        import webbrowser

        url = f"http://{args.host}:{args.port}/viewer/index.html"

        def _open() -> None:
            webbrowser.open(url)

        threading.Timer(0.8, _open).start()
        print(f"正在打开浏览器: {url}")
        print("服务运行中，按 Ctrl+C 停止。")
        run_until_shutdown(server, server_state)
        return

    try:
        _run_viewer_gui(
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


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        print(f"启动失败: {exc}", file=sys.stderr)
        traceback.print_exc()
        if sys.platform == "win32":
            input("按 Enter 键退出...")
        raise SystemExit(1) from exc
