#!/usr/bin/env python3
"""Export interactive map web assets from map_editor.sqlite (offline snapshot)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.db_reader import load_names_json, load_names_json_merged_all_locales  # noqa: E402
from interactive_map.map_session import JSON_DOCUMENTS, LAYER_NAMES, MapSession  # noqa: E402
from src.editor_config import load_config  # noqa: E402

_LAYER_FILES = {
    "ownership": "ownership.png",
    "country_type": "country_type.png",
    "terrain": "terrain.png",
    "incorporation": "incorporation.png",
    "homeland": "homeland.png",
    "claims": "claims.png",
    "foreign_investment": "foreign_investment.png",
    "building_level": "building_level.png",
    "slavery": "slavery.png",
    "pop_total": "pop_total.png",
    "pop_culture": "pop_culture.png",
    "pop_religion": "pop_religion.png",
    "hubs": "hubs.png",
    "strategic_region": "strategic_region.png",
    "raw": "raw.png",
    "border_province": "border_province.png",
    "border_state": "border_state.png",
    "border_country": "border_country.png",
}


def export_web_data(db_path: Path, output_dir: Path) -> None:
    """Write a static web/ snapshot (for CI or offline viewing). Runtime editor uses api_server."""
    output_dir.mkdir(parents=True, exist_ok=True)
    web_dir = output_dir / "web"
    if web_dir.exists():
        shutil.rmtree(web_dir)
    web_dir.mkdir(parents=True, exist_ok=True)

    session = MapSession.open(db_path)
    try:
        (web_dir / "provinces.png").write_bytes(session.provinces_png())
        for doc in JSON_DOCUMENTS:
            payload = session.meta_json() if doc == "meta" else session.json_document(doc)
            indent = None if doc == "provinces" else 2
            separators = (",", ":") if doc == "provinces" else (",", ": ")
            (web_dir / f"{doc}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=indent, separators=separators),
                encoding="utf-8",
            )
        for layer in LAYER_NAMES:
            (web_dir / _LAYER_FILES[layer]).write_bytes(session.layer_png(layer))
        config = load_config()
        names = load_names_json_merged_all_locales(session.conn, config.vanilla)
        (web_dir / "names.json").write_text(
            json.dumps(names, ensure_ascii=False, indent=2, separators=(",", ": ")),
            encoding="utf-8",
        )
        zh_names = names["zh"]
        meta = session.meta_json()
        meta["tag_name_count"] = len(zh_names["tags"])
        meta["state_name_count"] = len(zh_names["states"])
        meta["hub_name_count"] = len(zh_names["hubs"])
        meta["culture_name_count"] = len(zh_names["cultures"])
        meta["religion_name_count"] = len(zh_names["religions"])
        meta["building_name_count"] = len(zh_names["buildings"])
        meta["building_group_name_count"] = len(zh_names["building_groups"])
        meta["pm_name_count"] = len(zh_names["pms"])
        meta["company_name_count"] = len(zh_names["companies"])
        (web_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, separators=(",", ": ")),
            encoding="utf-8",
        )
    finally:
        session.close()

    print(f"导出完成: {web_dir}")
    print(f"  数据库: {db_path.name}")
    print(f"  地块: {meta['province_count']}")
    print(f"  tag+state: {meta['state_count']}")
    print(f"  领土着色像素: {meta['ownership_pixels']} / {meta['total_pixels']}")
    print(f"  优质地块: {meta['prime_land_count']}")
    print(f"  普通地块: {meta['normal_land_count']}")
    print(f"  不可通行: {meta['impassable_count']}")
    print(f"  已整合地块: {meta['incorporated_provinces']}")
    print(f"  未整合地块: {meta['unincorporated_provinces']}")
    print(f"  枢纽地块: {meta['hub_provinces']}")
    print(f"  tag 名: {meta['tag_name_count']}")
    print(f"  州名: {meta['state_name_count']}")
    print(f"  城市名: {meta['hub_name_count']}")
    print(f"  文化名: {meta['culture_name_count']}")
    print(f"  宗教名: {meta['religion_name_count']}")
    print(f"  建筑名: {meta['building_name_count']}")
    print(f"  建筑组名: {meta['building_group_name_count']}")
    print(f"  PM 名: {meta['pm_name_count']}")
    print(f"  公司名: {meta['company_name_count']}")
    print(f"  尺寸: {meta['width']} x {meta['height']}")


def main() -> None:
    default_db = ROOT / "output" / "map_editor.sqlite"
    default_out = ROOT / "interactive_map" / "output" / "view"

    parser = argparse.ArgumentParser(
        description="从 map_editor.sqlite 导出静态 web 快照（编辑器运行时请用 api_server）"
    )
    parser.add_argument("database", type=Path, nargs="?", default=default_db)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_out,
        help="输出目录（默认 地图编辑器/interactive_map/output/view）",
    )
    args = parser.parse_args()

    if not args.database.is_file():
        raise SystemExit(f"找不到数据库：{args.database}")

    export_web_data(args.database.resolve(), args.output_dir)


if __name__ == "__main__":
    main()
