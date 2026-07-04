"""1836 market subordination forest from history diplomacy + customs-union power blocs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from history_pops_flat import _find_block_end
from vic3_assign import VIC3_ASSIGN as A, prepare_game_content, read_game_content

COUNTRY_BLOCK_RE = re.compile(rf"c:(\w+)\s*{A}\s*\{{")
PACT_RE = re.compile(rf"create_diplomatic_pact\s*{A}\s*\{{([^}}]*)\}}", re.DOTALL)
CUSTOMS_UNION_IDENTITY_RE = re.compile(rf"identity\s*{A}\s*identity_trade_league")

# create_diplomatic_pact：黑名单之外均视为市场从属（含模组自定义属国类型）。
NON_SUBORDINATE_PACT_TYPES = frozenset({
    # 独立市场 / 双边关系
    "grant_own_market",
    "rivalry",
    "embargo",
    "disapproval_pact",
    "raiding_pact",
    "increase_relations",
    "damage_relations",
    "trade_states",
    "colonization_rights",
    "humiliation",
    "war_reparations",
    "violate_sovereignty",
    "expel_diplomats",
    "redeem_obligation",
    "enforce_military_access",
    "invite_to_power_bloc",
    "join_power_bloc",
    "fund_lobbies",
    "force_become_subject",
    "force_state_religion",
    "force_regime_change",
    "add_power_bloc_culture",
    "orchestrate_coup",
    "support_separatism",
    "da_stake_colonial_claim",
    "invoke_doctrine_of_lapse",
    "grant_state",
    "take_state",
    "demand_state",
    # 属国修饰条约（不建立宗属关系）
    "decrease_payments",
    "raise_payments",
    "exempt_from_service",
    "da_decrease_autonomy",
    "da_increase_autonomy_of_subject",
    "da_increase_autonomy_of_self",
    "da_appoint_colonial_governor",
    "da_request_colonial_governor",
    "da_subject_request_investment_rights",
    "da_overlord_grant_investment_rights",
    "da_change_culture",
    "da_support_regime",
    "da_request_support_regime",
    "da_evangelize",
    "da_knowledge_sharing",
    "da_request_knowledge_sharing",
    "request_market_control",
})


@dataclass(frozen=True)
class MarketSubordinationRow:
    tag: str
    market_master: str


def _read_block_body(text: str, header_end: int) -> str:
    start = header_end - 1
    end = _find_block_end(text, start)
    return text[start + 1 : end]


def _parse_subject_relationships(text: str) -> tuple[dict[str, str], set[str]]:
    """Return (subject -> overlord, grant_own_market tags)."""
    parent: dict[str, str] = {}
    own_market: set[str] = set()

    for block in COUNTRY_BLOCK_RE.finditer(text):
        overlord = block.group(1)
        body = _read_block_body(text, block.end())
        for m in PACT_RE.finditer(body):
            inner = m.group(1)
            country_m = re.search(rf"country\s*{A}\s*c:(\w+)", inner)
            type_m = re.search(rf"type\s*{A}\s*(\w+)", inner)
            if not country_m or not type_m:
                continue
            subject = country_m.group(1)
            pact_type = type_m.group(1)
            if pact_type == "grant_own_market":
                own_market.add(subject)
            elif pact_type not in NON_SUBORDINATE_PACT_TYPES:
                parent[subject] = overlord

    return parent, own_market


def _parse_customs_union_members(text: str) -> dict[str, str]:
    """Return customs-union member -> bloc leader (trade league only)."""
    parent: dict[str, str] = {}
    for block in COUNTRY_BLOCK_RE.finditer(text):
        leader = block.group(1)
        body = _read_block_body(text, block.end())
        if not CUSTOMS_UNION_IDENTITY_RE.search(body):
            continue
        for m in re.finditer(rf"member\s*{A}\s*c:(\w+)", body):
            parent.setdefault(m.group(1), leader)
    return parent


def parse_market_subordination(
    *,
    subject_relationships: Path,
    power_blocs: Path,
) -> tuple[list[MarketSubordinationRow], set[str]]:
    subject_text = read_game_content(subject_relationships)
    bloc_text = read_game_content(power_blocs)
    return parse_market_subordination_text(
        subject_text=subject_text,
        bloc_text=bloc_text,
    )


def parse_market_subordination_text(
    *,
    subject_text: str,
    bloc_text: str,
) -> tuple[list[MarketSubordinationRow], set[str]]:
    subject_text = prepare_game_content(subject_text)
    bloc_text = prepare_game_content(bloc_text)

    parent, own_market = _parse_subject_relationships(subject_text)
    for member, leader in _parse_customs_union_members(bloc_text).items():
        parent.setdefault(member, leader)

    for tag in own_market:
        parent.pop(tag, None)

    rows = [
        MarketSubordinationRow(tag=tag, market_master=master)
        for tag, master in sorted(parent.items())
    ]
    return rows, own_market


def parse_market_subordination_dirs(
    diplomacy_dir: Path | None = None,
    power_blocs_dir: Path | None = None,
    *,
    diplomacy_paths: list[Path] | tuple[Path, ...] | None = None,
    power_blocs_paths: list[Path] | tuple[Path, ...] | None = None,
    diplomacy_mod_dir: Path | None = None,
    power_blocs_mod_dir: Path | None = None,
) -> tuple[list[MarketSubordinationRow], set[str]]:
    from game_content_resolver import read_txt_dir, read_txt_paths, read_txt_paths_mod_over_vanilla

    if diplomacy_paths is None:
        if diplomacy_dir is None:
            raise ValueError("必须提供 diplomacy_dir 或 diplomacy_paths 参数")
        subject_text = read_txt_dir(diplomacy_dir)
    elif diplomacy_mod_dir is not None:
        subject_text = read_txt_paths_mod_over_vanilla(diplomacy_paths, diplomacy_mod_dir)
    else:
        subject_text = read_txt_paths(diplomacy_paths)

    if power_blocs_paths is None:
        if power_blocs_dir is None:
            raise ValueError("必须提供 power_blocs_dir 或 power_blocs_paths 参数")
        bloc_text = read_txt_dir(power_blocs_dir)
    elif power_blocs_mod_dir is not None:
        bloc_text = read_txt_paths_mod_over_vanilla(power_blocs_paths, power_blocs_mod_dir)
    else:
        bloc_text = read_txt_paths(power_blocs_paths)

    return parse_market_subordination_text(
        subject_text=subject_text,
        bloc_text=bloc_text,
    )


def market_root(tag: str, rows: list[MarketSubordinationRow]) -> str:
    parent = {r.tag: r.market_master for r in rows}
    cur = tag
    seen: set[str] = set()
    while cur in parent:
        if cur in seen:
            raise ValueError(f"market_subordination 存在循环，节点：{cur}")
        seen.add(cur)
        cur = parent[cur]
    return cur


def rows_to_json(rows: list[MarketSubordinationRow]) -> list[dict[str, str]]:
    return [{"tag": r.tag, "market_master": r.market_master} for r in rows]


def export_excel(rows: list[MarketSubordinationRow], path: Path) -> Path:
    from openpyxl import Workbook

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "market_subordination"
    ws.append(["tag", "market_master"])
    for row in rows:
        ws.append([row.tag, row.market_master])
    wb.save(path)
    return path


def export_json(
    rows: list[MarketSubordinationRow],
    path: Path,
    *,
    own_market: set[str],
) -> Path:
    payload: dict[str, Any] = {
        "own_market": sorted(own_market),
        "subordination": rows_to_json(rows),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
