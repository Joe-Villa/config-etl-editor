"""Per-mod rules for forcing vanilla content for selected folders."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from constants import PACKAGE_ROOT

PROFILES_DIR = PACKAGE_ROOT / "profiles"

ALL_CONTENT_PATHS: tuple[str, ...] = (
    "map_data/state_regions",
    "common/history/pops",
    "common/history/diplomacy",
    "common/history/power_blocs",
    "common/history/states",
    "common/history/buildings",
    "common/history/countries",
    "common/country_definitions",
)


@dataclass(frozen=True)
class ContentPolicy:
    """Control which mod folders are used vs forced back to vanilla."""

    mod_only: frozenset[str] = frozenset()
    force_vanilla: frozenset[str] = frozenset()

    def uses_mod(self, relative: str) -> bool:
        if self.mod_only:
            return relative in self.mod_only
        if relative in self.force_vanilla:
            return False
        return True

    def forced_vanilla_paths(self) -> frozenset[str]:
        if self.mod_only:
            return frozenset(p for p in ALL_CONTENT_PATHS if p not in self.mod_only)
        return self.force_vanilla

    def to_dict(self) -> dict:
        payload: dict = {}
        if self.mod_only:
            payload["mod_only"] = sorted(self.mod_only)
        if self.force_vanilla:
            payload["force_vanilla"] = sorted(self.force_vanilla)
        return payload


def _normalize_paths(paths: list[str]) -> frozenset[str]:
    return frozenset(p.strip().strip("/") for p in paths if p and p.strip())


def content_policy_from_dict(data: dict) -> ContentPolicy:
    mod_only = _normalize_paths(list(data.get("mod_only", [])))
    force_vanilla = _normalize_paths(list(data.get("force_vanilla", [])))
    if mod_only and force_vanilla:
        raise ValueError("内容策略不能同时设置 mod_only 与 force_vanilla")
    unknown = (mod_only | force_vanilla) - set(ALL_CONTENT_PATHS)
    if unknown:
        raise ValueError(f"内容策略中存在未知路径：{sorted(unknown)}")
    return ContentPolicy(mod_only=mod_only, force_vanilla=force_vanilla)


def load_profile(run_id: str) -> ContentPolicy | None:
    path = PROFILES_DIR / f"{run_id}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return content_policy_from_dict(data)


def merge_policies(*policies: ContentPolicy | None) -> ContentPolicy:
    mod_only: set[str] | None = None
    force_vanilla: set[str] = set()
    for policy in policies:
        if policy is None:
            continue
        if policy.mod_only:
            mod_only = set(policy.mod_only)
        force_vanilla.update(policy.force_vanilla)
    if mod_only is not None and force_vanilla:
        raise ValueError("不能将 mod_only 与 force_vanilla 合并使用")
    return ContentPolicy(
        mod_only=frozenset(mod_only or ()),
        force_vanilla=frozenset(force_vanilla),
    )
