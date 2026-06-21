"""Load map editor config.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PACKAGE_ROOT / "config.json"
SCHEMA_PATH = PACKAGE_ROOT / "schema.sql"


@dataclass(frozen=True)
class MapEditorConfig:
    vanilla: Path


def load_config(path: Path | None = None) -> MapEditorConfig:
    config_path = (path or CONFIG_PATH).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"未找到配置文件：{config_path}")
    data = json.loads(config_path.read_text(encoding="utf-8"))
    vanilla_raw = data.get("vanilla")
    if not vanilla_raw or not str(vanilla_raw).strip():
        raise ValueError(f"config.json 中必须配置 vanilla 路径：{config_path}")
    vanilla = Path(str(vanilla_raw)).expanduser()
    if not vanilla.is_dir():
        raise FileNotFoundError(f"vanilla 路径不存在：{vanilla}")
    return MapEditorConfig(vanilla=vanilla)
