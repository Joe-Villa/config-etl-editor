"""Parse hub_names_l_simp_chinese.yml and attach names to state_region rows."""

from __future__ import annotations

import re
from pathlib import Path

from state_region_flat import FlatStateRegion

HUB_TYPES = ("city", "port", "farm", "mine", "wood")
_HUB_NAME_RE = re.compile(
    r'^\s*HUB_NAME_(STATE_\w+)_(city|port|farm|mine|wood):\s*"([^"]*)"',
    re.MULTILINE,
)


def default_hub_names_path(game_root: Path) -> Path:
    return game_root / "localization" / "simp_chinese" / "hub_names_l_simp_chinese.yml"


def load_hub_names(path: Path) -> dict[tuple[str, str], str]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return {
        (state, hub_type): name
        for state, hub_type, name in _HUB_NAME_RE.findall(text)
    }


def apply_hub_names_to_regions(
    rows: list[FlatStateRegion],
    hub_names: dict[tuple[str, str], str],
) -> None:
    for row in rows:
        for hub in HUB_TYPES:
            province = getattr(row, hub)
            name = hub_names.get((row.state, hub), "") if province else ""
            setattr(row, f"{hub}_name", name)
