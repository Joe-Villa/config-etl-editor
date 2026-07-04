"""Load collect_origin_data/config.json (required on every run)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from constants import PACKAGE_ROOT
from content_policy import ALL_CONTENT_PATHS, _normalize_paths

CONFIG_PATH = PACKAGE_ROOT / "config.json"


@dataclass(frozen=True)
class CollectConfig:
    metadata_hide_full_path: bool
    vanilla: Path
    force_to_vanilla: frozenset[str]

    def content_policy(self):
        from content_policy import ContentPolicy

        return ContentPolicy(force_vanilla=self.force_to_vanilla)


def load_config(path: Path | None = None) -> CollectConfig:
    config_path = (path or CONFIG_PATH).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(
            f"未找到配置文件：{config_path}\n"
            "请创建 collect_origin_data/config.json 并填写本机原版 game 路径"
        )

    data = json.loads(config_path.read_text(encoding="utf-8"))
    vanilla_raw = data.get("vanilla")
    if not vanilla_raw or not str(vanilla_raw).strip():
        raise ValueError(f"config.json 中必须配置 vanilla 路径：{config_path}")

    force_to_vanilla = _normalize_paths(list(data.get("force_to_vanilla", [])))
    unknown = force_to_vanilla - set(ALL_CONTENT_PATHS)
    if unknown:
        raise ValueError(f"config 中存在未知的 force_to_vanilla 路径：{sorted(unknown)}")

    return CollectConfig(
        metadata_hide_full_path=bool(data.get("metadata_hide_full_path", False)),
        vanilla=Path(str(vanilla_raw)).expanduser(),
        force_to_vanilla=force_to_vanilla,
    )
