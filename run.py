#!/usr/bin/env python3
"""Build map editor sqlite from vanilla or mod game content."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app_paths import default_save_sqlite  # noqa: E402

from build_db import build_map_db, resolve_build_output_path  # noqa: E402
from editor_config import MapEditorConfig, load_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="从游戏/mod 内容构建地图编辑器数据库")
    parser.add_argument(
        "mod_root",
        type=Path,
        nargs="?",
        default=None,
        help="模组根目录；省略则仅使用 vanilla",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=default_save_sqlite(),
        help="输出 sqlite 路径",
    )
    parser.add_argument(
        "--allow-errors",
        action="store_true",
        help="存在 error 时仍写出数据库",
    )
    parser.add_argument(
        "--skip-map-images",
        action="store_true",
        help="跳过地图图片计算（测试用；输出文件名前加 test）",
    )
    parser.add_argument(
        "--vanilla",
        type=Path,
        default=None,
        help="原版 game 目录（默认读 config.json）",
    )
    args = parser.parse_args()

    config = load_config()
    if args.vanilla is not None:
        config = MapEditorConfig(vanilla=args.vanilla.resolve())
    mod_root = args.mod_root.resolve() if args.mod_root else config.vanilla
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = resolve_build_output_path(args.output, skip_map_images=args.skip_map_images)

    print(f"vanilla: {config.vanilla}")
    print(f"mod_root: {mod_root}")
    print(f"output: {output}")

    log = build_map_db(
        mod_root,
        args.output,
        config,
        fail_on_error=not args.allow_errors,
        skip_map_images=args.skip_map_images,
    )
    log.print_summary()

    if not log.ok:
        raise SystemExit(1)

    conn_counts = __import__("sqlite3").connect(output)
    tables = [
        "ref_religion",
        "ref_culture",
        "ref_tag_culture",
        "ref_tag",
        "ref_sr",
        "geo_state",
        "st",
        "st_pop",
        "st_bld",
    ]
    print("表行数：")
    for name in tables:
        n = conn_counts.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {n}")
    conn_counts.close()

    print("完成。")


if __name__ == "__main__":
    main()
