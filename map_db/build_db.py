"""Build map editor sqlite from game/mod content."""

from __future__ import annotations

import os
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import *  # noqa: F403
from content_paths import mod_replace_paths, resolve_game_content
from editor_config import SCHEMA_PATH, MapEditorConfig
from game_content_resolver import split_merged_paths
from history_states_flat import StateOwnershipRow
from parse_edit import (
    BuildingSite,
    PopRow,
    load_history_buildings,
    load_history_pops,
    load_history_states,
)
from parse_ref import (
    SUPPORTED_LOCALES,
    load_state_regions,
    merge_tag_rows,
    parse_building_groups_paths,
    parse_buildings_paths,
    parse_company_types_paths,
    parse_cultures_paths,
    parse_localization_merged,
    parse_pm_groups_paths,
    parse_religions_paths,
    parse_strategic_regions_paths,
    resolve_provinces_png,
    resolve_root_groups,
)
from state_region_flat import (
    build_authoritative_province_state,
    build_province_state_index,
    states_defined_in_mod_map_data,
    validate_mod_map_data_state_regions,
    SEA_STATE_ID_MIN,
    is_land_state,
)
from util import norm_province
from history_source_index import insert_history_index
from warn import ImportLog


class BuildMapDbError(RuntimeError):
    """Raised when import errors prevent a successful database build."""

    def __init__(self, log: ImportLog) -> None:
        self.log = log
        super().__init__(f"建库失败：{len(log.errors)} 个错误")


def _sqlite_sidecar_paths(db_path: Path) -> tuple[Path, Path]:
    return Path(f"{db_path}-wal"), Path(f"{db_path}-shm")


def _remove_db_files(db_path: Path) -> None:
    for path in (db_path, *_sqlite_sidecar_paths(db_path)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _building_db_path(output: Path) -> Path:
    return output.with_suffix(output.suffix + ".building")


def resolve_build_output_path(output: Path, *, skip_map_images: bool) -> Path:
    """When skipping map images, prefix the filename with ``test`` (test-only database)."""
    output = output.resolve()
    if not skip_map_images:
        return output
    return output.with_name(f"test{output.name}")


def _finalize_db_build(tmp: Path, output: Path) -> None:
    for path in _sqlite_sidecar_paths(output):
        path.unlink(missing_ok=True)
    os.replace(tmp, output)
    for path in _sqlite_sidecar_paths(tmp):
        path.unlink(missing_ok=True)


BUILD_TEXT_STAGE_COUNT = 18
BUILD_STATIC_LAYER_COUNT = 5
BUILD_TOTAL_STAGES = BUILD_TEXT_STAGE_COUNT + BUILD_STATIC_LAYER_COUNT

_progress_callback: Callable[[str], None] | None = None


def _progress(label: str) -> None:
    print(f"正在阅读{label}信息", flush=True)
    if _progress_callback is not None:
        _progress_callback(label)


def _merged_paths(
    mod_root: Path,
    vanilla: Path,
    relative: str,
    replace_paths: frozenset[str],
) -> tuple[Path, ...]:
    merged = resolve_game_content(mod_root, relative, vanilla, replace_paths)
    return merged.paths


def _split_vanilla_mod(paths: tuple[Path, ...], mod_root: Path, relative: str) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    mod_dir = mod_root / relative
    vanilla_paths, mod_paths = split_merged_paths(list(paths), mod_dir)
    return tuple(vanilla_paths), tuple(mod_paths)


def _pm_index(conn: sqlite3.Connection) -> dict[str, list[str]]:
    pm_by_pmg: dict[str, list[str]] = {}
    for pmg, pm, ord_ in conn.execute(
        "SELECT pm_group, pm, ord FROM ref_pmg_pm ORDER BY pm_group, ord"
    ):
        pm_by_pmg.setdefault(pmg, []).append(pm)
    return pm_by_pmg


def _building_pmgs(conn: sqlite3.Connection) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for building, pmg, _ord in conn.execute(
        "SELECT building, pm_group, ord FROM ref_bld_pmg ORDER BY building, ord"
    ):
        out.setdefault(building, []).append(pmg)
    return out


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _pm_groups_for_pm_on_building(
    pm: str,
    expected_pmgs: list[str],
    pm_by_pmg: dict[str, list[str]],
) -> list[str]:
    return [pmg for pmg in expected_pmgs if pm in pm_by_pmg.get(pmg, [])]


def _pm_groups_containing(pm: str, pm_by_pmg: dict[str, list[str]]) -> list[str]:
    return [pmg for pmg, pms in pm_by_pmg.items() if pm in pms]


def _buildings_using_pm_groups(
    pmgs: list[str],
    building_pmgs: dict[str, list[str]],
    exclude_building: str | None = None,
) -> list[str]:
    pmg_set = set(pmgs)
    out: list[str] = []
    for building, groups in building_pmgs.items():
        if exclude_building and building == exclude_building:
            continue
        if pmg_set.intersection(groups):
            out.append(building)
    return sorted(out)


def normalize_site_pms(
    site: BuildingSite,
    pm_by_pmg: dict[str, list[str]],
    building_pmgs: dict[str, list[str]],
    log: ImportLog,
) -> list[str]:
    expected_pmgs = building_pmgs.get(site.building, [])
    if not expected_pmgs:
        return list(site.pm)

    scope = f"{site.tag}/{site.state}/{site.building}"
    chosen: dict[str, str] = {}
    for pm in _dedupe_preserve_order(site.pm):
        matching_pmgs = _pm_groups_for_pm_on_building(pm, expected_pmgs, pm_by_pmg)
        if not matching_pmgs:
            other_pmgs = _pm_groups_containing(pm, pm_by_pmg)
            if other_pmgs:
                other_buildings = _buildings_using_pm_groups(
                    other_pmgs, building_pmgs, exclude_building=site.building
                )
                detail = f"属于 PM 组 {other_pmgs}"
                if other_buildings:
                    detail += f"，建筑 {other_buildings}"
                log.warn(
                    f"建筑 {scope}：PM {pm} 不属于本建筑的 PM 组（{detail}），已忽略"
                )
            else:
                log.warn(f"建筑 {scope}：PM {pm} 不在 PM 目录，已忽略")
            continue
        if len(matching_pmgs) > 1:
            log.warn(
                f"建筑 {scope}：PM {pm} 同时属于多个 PM 组 "
                f"{matching_pmgs}，使用 {matching_pmgs[0]}"
            )
        pmg = matching_pmgs[0]
        if pmg in chosen and chosen[pmg] != pm:
            log.warn(
                f"建筑 {scope}：PM 组 {pmg} 出现多个 PM，保留 {chosen[pmg]}"
            )
            continue
        chosen[pmg] = pm

    result: list[str] = []
    for pmg in expected_pmgs:
        if pmg in chosen:
            result.append(chosen[pmg])
            continue
        pms = pm_by_pmg.get(pmg, [])
        if not pms:
            continue
        result.append(pms[0])
    return result


def warn_duplicate_building_pm_mismatch(
    site: BuildingSite,
    pm_list: list[str],
    seen: dict[tuple[str, str, str], list[str]],
    log: ImportLog,
) -> None:
    """Warn when the same tag/state/building appears more than once with different PMs."""
    key = (site.state, site.tag, site.building)
    prev = seen.get(key)
    if prev is None:
        seen[key] = list(pm_list)
        return
    if prev == pm_list:
        return
    scope = f"{site.tag}/{site.state}/{site.building}"
    log.warn(
        f"建筑 {scope}：多处 create_building 的 PM 不一致"
        f"（已有 {prev}，当前 {pm_list}）"
    )


def _merge_ownership_rows(
    rows: list[StateOwnershipRow],
    log: ImportLog,
) -> list[StateOwnershipRow]:
    """Union owned_provinces when the same (state, tag) appears in multiple create_state blocks."""
    merged: dict[tuple[str, str], StateOwnershipRow] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        key = (row.state, row.tag)
        if key not in merged:
            merged[key] = row
            order.append(key)
            continue
        prev = merged[key]
        seen = set(prev.owned_provinces)
        new_provs = [p for p in row.owned_provinces if p not in seen]
        log.warn(
            f"ownership {row.state}/{row.tag}：重复 create_state，"
            f"已并入 {len(new_provs)} 个新 province"
        )
        merged[key] = StateOwnershipRow(
            state=row.state,
            tag=row.tag,
            owned_provinces=prev.owned_provinces + new_provs,
            state_type=row.state_type or prev.state_type,
            population=prev.population + row.population,
        )
    return [merged[k] for k in order]


@dataclass(frozen=True)
class ProvinceOwner:
    state: str
    tag: str


def resolve_clean_province_owners(
    ownership_rows: list[StateOwnershipRow],
    province_to_state: dict[str, str],
    valid_tags: set[str],
    valid_states: set[str],
    log: ImportLog,
) -> tuple[list[StateOwnershipRow], dict[str, ProvinceOwner]]:
    """Resolve history ownership claims onto map_data provinces.

  Authority model
  ---------------
  * **map_data** (``province_to_state``, ``valid_states``): each province maps to
    exactly one state; ambiguous map_data is rejected earlier at ingest.
  * **history** (``ownership_rows``): best-effort for state/province. Unknown
    state rows and provinces absent from map_data are warned and dropped.
    **Undefined tag is always an error** — authors must declare every tag they use.
  * **Output**: each province in ``owners`` has exactly one ``(state, tag)``.
    Conflicting claims are collapsed with warnings (later claim wins).

  Hard errors are reserved for ``_check_unowned_land_provinces``: a land state
  defined in map_data whose provinces are entirely unclaimed by any tag.
    """
    st_rows: list[StateOwnershipRow] = []
    owners: dict[str, ProvinceOwner] = {}

    for row in ownership_rows:
        if row.tag not in valid_tags:
            log.error(f"ownership {row.state}/{row.tag}：未定义的 tag")
            continue
        if row.state not in valid_states:
            log.warn(
                f"ownership {row.state}/{row.tag}：不在 map_data/state_regions 中，"
                f"history 行已忽略"
            )
            continue
        st_rows.append(row)
        seen_in_row: set[str] = set()
        for prov in row.owned_provinces:
            prov = norm_province(prov)
            if not prov:
                continue
            if prov in seen_in_row:
                log.warn(f"{row.tag}/{row.state} province {prov}：重复，已忽略")
                continue
            seen_in_row.add(prov)
            map_state = province_to_state.get(prov)
            if map_state is None:
                log.warn(
                    f"{row.tag}/{row.state} province {prov}："
                    f"history 引用但不在 map_data/state_regions 中，已忽略"
                )
                continue
            effective_state = row.state
            if map_state != row.state:
                log.warn(
                    f"{row.tag}/{row.state} province {prov}："
                    f"history/states 归属 {row.state} 与 map_data {map_state} 不一致，"
                    f"已按 map_data 改为 {map_state}"
                )
                effective_state = map_state
            if effective_state not in valid_states:
                log.warn(
                    f"{row.tag}/{row.state} province {prov}："
                    f"map_data 归属 {effective_state} 不在 state_regions，已忽略"
                )
                continue
            new_owner = ProvinceOwner(effective_state, row.tag)
            prev = owners.get(prov)
            if prev is None:
                owners[prov] = new_owner
                continue
            if prev.state == new_owner.state and prev.tag == new_owner.tag:
                continue
            log.warn(
                f"{row.tag}/{row.state} province {prov}："
                f"与 {prev.tag}/{prev.state} 冲突，归属改为 {row.tag}/{new_owner.state}"
            )
            owners[prov] = new_owner

    return st_rows, owners


def _insert_st_and_province_owners(
    conn: sqlite3.Connection,
    st_rows: list[StateOwnershipRow],
    owners: dict[str, ProvinceOwner],
) -> set[tuple[str, str]]:
    st_keys: set[tuple[str, str]] = set()
    state_type_by_key: dict[tuple[str, str], str] = {
        (row.state, row.tag): row.state_type or "incorporated" for row in st_rows
    }
    state_type_by_tag = {
        row.tag: row.state_type or "incorporated" for row in st_rows
    }

    def _ensure_st(state: str, tag: str) -> None:
        key = (state, tag)
        if key in st_keys:
            return
        conn.execute("INSERT OR IGNORE INTO geo_state (state) VALUES (?)", (state,))
        conn.execute(
            "INSERT INTO st (state, tag, state_type) VALUES (?, ?, ?)",
            (
                state,
                tag,
                state_type_by_key.get(key, state_type_by_tag.get(tag, "incorporated")),
            ),
        )
        st_keys.add(key)

    for row in st_rows:
        _ensure_st(row.state, row.tag)
    for prov, owner in owners.items():
        _ensure_st(owner.state, owner.tag)
        conn.execute(
            "INSERT INTO st_prov (province, state, tag) VALUES (?, ?, ?)",
            (prov, owner.state, owner.tag),
        )
    return st_keys


def _validate_st_prov_integrity(conn: sqlite3.Connection, log: ImportLog) -> None:
    """Align st_prov with map_data; warn and drop rows outside ref_sr_prov."""
    for province, in conn.execute(
        """
        SELECT sp.province
        FROM st_prov sp
        LEFT JOIN ref_sr_prov rp ON rp.province = sp.province
        WHERE rp.province IS NULL
        """
    ):
        log.warn(
            f"province {province}：不在 map_data/state_regions 中，已从 st_prov 移除"
        )
        conn.execute("DELETE FROM st_prov WHERE province = ?", (province,))

    for province, state, map_state in conn.execute(
        """
        SELECT sp.province, sp.state, rp.state
        FROM st_prov sp
        JOIN ref_sr_prov rp ON rp.province = sp.province
        WHERE sp.state != rp.state
        """
    ):
        tag_row = conn.execute(
            "SELECT tag FROM st_prov WHERE province = ?", (province,)
        ).fetchone()
        if tag_row is None:
            continue
        tag = str(tag_row[0])
        log.warn(
            f"province {province}：history/states 归属 {state} 与 map_data {map_state} 不一致，"
            f"已按 map_data 改为 {map_state}"
        )
        conn.execute("INSERT OR IGNORE INTO geo_state (state) VALUES (?)", (map_state,))
        conn.execute(
            """
            INSERT OR IGNORE INTO st (state, tag, state_type)
            VALUES (?, ?, 'incorporated')
            """,
            (map_state, tag),
        )
        conn.execute(
            "UPDATE st_prov SET state = ? WHERE province = ?",
            (map_state, province),
        )

    for province, state, tag in conn.execute(
        """
        SELECT sp.province, sp.state, sp.tag
        FROM st_prov sp
        LEFT JOIN st ON st.state = sp.state AND st.tag = sp.tag
        WHERE st.state IS NULL
        """
    ):
        log.error(
            f"province {province}：states 归属 ({state}, {tag}) 不在 st 表"
        )


def _mod_content_dir(mod_root: Path, relative: str) -> Path:
    return mod_root / relative


def _insert_ref_catalogs(
    conn: sqlite3.Connection,
    mod_root: Path,
    vanilla: Path,
    log: ImportLog,
    replace_paths: frozenset[str],
) -> None:
    _progress("宗教")
    rel_paths = _merged_paths(mod_root, vanilla, "common/religions", replace_paths)
    for row in parse_religions_paths(
        rel_paths,
        _mod_content_dir(mod_root, "common/religions"),
        warnings=log.warnings,
    ):
        conn.execute(
            """
            INSERT INTO ref_religion (religion, r, g, b, name_zh, name_en)
            VALUES (?, ?, ?, ?, '', '')
            """,
            (row.religion, row.r, row.g, row.b),
        )

    _progress("文化")
    culture_paths = _merged_paths(mod_root, vanilla, "common/cultures", replace_paths)
    cultures = parse_cultures_paths(
        culture_paths, _mod_content_dir(mod_root, "common/cultures")
    )
    valid_religions = {r[0] for r in conn.execute("SELECT religion FROM ref_religion")}
    for row in cultures:
        if row.default_religion not in valid_religions:
            log.warn(f"文化 {row.culture}：默认宗教 {row.default_religion} 不在白名单，已跳过")
            continue
        conn.execute(
            "INSERT INTO ref_culture (culture, default_religion, r, g, b) VALUES (?, ?, ?, ?, ?)",
            (row.culture, row.default_religion, row.r, row.g, row.b),
        )

    _progress("建筑组")
    bg_paths = _merged_paths(mod_root, vanilla, "common/building_groups", replace_paths)
    bg_rows = parse_building_groups_paths(
        bg_paths, _mod_content_dir(mod_root, "common/building_groups")
    )
    roots = resolve_root_groups(bg_rows)
    by_bg = {row.building_group: row for row in bg_rows}
    inserted_bg: set[str] = set()

    def _insert_bg(key: str) -> None:
        if key in inserted_bg:
            return
        row = by_bg[key]
        if row.parent_group and row.parent_group in by_bg:
            _insert_bg(row.parent_group)
        conn.execute(
            """
            INSERT INTO ref_bg (building_group, parent_group, root_group)
            VALUES (?, ?, ?)
            """,
            (key, row.parent_group, roots[key]),
        )
        inserted_bg.add(key)

    for row in bg_rows:
        _insert_bg(row.building_group)

    _progress("生产方式组")
    pmg_paths = _merged_paths(
        mod_root, vanilla, "common/production_method_groups", replace_paths
    )
    pm_groups = parse_pm_groups_paths(
        pmg_paths, _mod_content_dir(mod_root, "common/production_method_groups")
    )
    for row in pm_groups:
        conn.execute("INSERT INTO ref_pmg (pm_group) VALUES (?)", (row.pm_group,))
        for ord_, pm in enumerate(row.pms):
            conn.execute(
                "INSERT INTO ref_pmg_pm (pm_group, ord, pm) VALUES (?, ?, ?)",
                (row.pm_group, ord_, pm),
            )

    _progress("建筑")
    bld_paths = _merged_paths(mod_root, vanilla, "common/buildings", replace_paths)
    buildings = parse_buildings_paths(
        bld_paths, _mod_content_dir(mod_root, "common/buildings")
    )
    valid_bg = {r[0] for r in conn.execute("SELECT building_group FROM ref_bg")}
    valid_pmg = {r[0] for r in conn.execute("SELECT pm_group FROM ref_pmg")}
    for row in buildings:
        if row.building_group not in valid_bg:
            log.warn(f"建筑 {row.building}：未知建筑组 {row.building_group}，已跳过")
            continue
        conn.execute(
            "INSERT INTO ref_bld (building, building_group, buildable) VALUES (?, ?, ?)",
            (row.building, row.building_group, 1 if row.buildable else 0),
        )
        for ord_, pmg in enumerate(row.pm_groups):
            if pmg not in valid_pmg:
                log.warn(f"建筑 {row.building}：未知 PM 组 {pmg}，已跳过")
                continue
            conn.execute(
                "INSERT INTO ref_bld_pmg (building, ord, pm_group) VALUES (?, ?, ?)",
                (row.building, ord_, pmg),
            )

    _progress("公司类型")
    co_paths = _merged_paths(mod_root, vanilla, "common/company_types", replace_paths)
    for company in parse_company_types_paths(
        co_paths, _mod_content_dir(mod_root, "common/company_types")
    ):
        conn.execute("INSERT INTO ref_co (company_type) VALUES (?)", (company,))

    _progress("命名颜色")
    from named_colors_flat import build_named_color_lookup, parse_named_colors_paths

    nc_paths = _merged_paths(mod_root, vanilla, "common/named_colors", replace_paths)
    named_color_rows = parse_named_colors_paths(
        nc_paths, mod_dir=_mod_content_dir(mod_root, "common/named_colors")
    )
    named_color_lookup = build_named_color_lookup(named_color_rows)
    for row in named_color_rows:
        conn.execute(
            """
            INSERT INTO ref_named_color (color_key, r, g, b)
            VALUES (?, ?, ?, ?)
            """,
            (row.key, row.r, row.g, row.b),
        )

    _progress("国家定义")
    cd_paths = _merged_paths(mod_root, vanilla, "common/country_definitions", replace_paths)
    v_paths, m_paths = _split_vanilla_mod(cd_paths, mod_root, "common/country_definitions")
    tag_rows = merge_tag_rows(
        v_paths,
        m_paths,
        mod_dir=_mod_content_dir(mod_root, "common/country_definitions"),
        mod_root=mod_root,
        vanilla=vanilla,
        log=log,
        named_colors=named_color_lookup,
    )
    valid_cultures = {r[0] for r in conn.execute("SELECT culture FROM ref_culture")}
    for row in tag_rows:
        conn.execute(
            """
            INSERT INTO ref_tag (tag, r, g, b, capital_state, country_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row.tag, row.r, row.g, row.b, row.capital_state, row.country_type or "recognized"),
        )
        for ord_, culture in enumerate(row.cultures):
            if culture not in valid_cultures:
                log.warn(
                    f"国家 {row.tag} culture {culture}：不在文化白名单，已跳过"
                )
                continue
            conn.execute(
                "INSERT INTO ref_tag_culture (tag, culture, ord) VALUES (?, ?, ?)",
                (row.tag, culture, ord_),
            )

    if not log.ok:
        return

    _progress("地区定义")
    validate_mod_map_data_state_regions(mod_root, vanilla, replace_paths, log)
    if not log.ok:
        return

    _, ownership_rows_for_sr = load_history_states(
        mod_root, vanilla, replace_paths, log=None
    )
    state_tags: dict[str, set[str]] = defaultdict(set)
    for row in ownership_rows_for_sr:
        state_tags[row.state].add(row.tag)

    sr_rows = load_state_regions(mod_root, vanilla, replace_paths)
    authority = build_authoritative_province_state(mod_root, vanilla, replace_paths)
    mod_states = states_defined_in_mod_map_data(mod_root, vanilla, replace_paths)
    province_index = build_province_state_index(
        sr_rows,
        log,
        authority=authority,
        mod_states=mod_states,
        state_tags=dict(state_tags),
    )
    if not log.ok:
        return
    for sr in sr_rows:
        conn.execute(
            """
            INSERT INTO ref_sr (state, sr_id, city, port, farm, mine, wood)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (sr.state, sr.id, norm_province(sr.city), norm_province(sr.port), norm_province(sr.farm), norm_province(sr.mine), norm_province(sr.wood)),
        )
    for prov, state in sorted(province_index.province_to_state.items()):
        conn.execute(
            "INSERT INTO ref_sr_prov (state, province) VALUES (?, ?)",
            (state, prov),
        )
    for sr in sr_rows:
        for prov in sr.prime_land.split(",") if sr.prime_land else []:
            prov = norm_province(prov.strip())
            if not prov:
                continue
            try:
                conn.execute(
                    "INSERT INTO ref_sr_prime (state, province) VALUES (?, ?)",
                    (sr.state, prov),
                )
            except sqlite3.IntegrityError:
                log.warn(f"state_region {sr.state} prime_land {prov}：不在 provinces 列表，已跳过")
        for prov in sr.impassable.split(",") if sr.impassable else []:
            prov = norm_province(prov.strip())
            if not prov:
                continue
            try:
                conn.execute(
                    "INSERT INTO ref_sr_impassable (state, province) VALUES (?, ?)",
                    (sr.state, prov),
                )
            except sqlite3.IntegrityError:
                log.warn(f"state_region {sr.state} impassable {prov}：不在 provinces 列表，已跳过")

    _progress("战略区域")
    strat_paths = _merged_paths(mod_root, vanilla, "common/strategic_regions", replace_paths)
    strat_mod_dir = _mod_content_dir(mod_root, "common/strategic_regions")
    valid_sr = {r[0] for r in conn.execute("SELECT state FROM ref_sr")}
    for row in parse_strategic_regions_paths(
        strat_paths,
        strat_mod_dir,
        mod_root=mod_root,
        vanilla=vanilla,
        log=log,
    ):
        conn.execute(
            """
            INSERT INTO ref_strat (region, capital_province, map_r, map_g, map_b)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row.region, row.capital_province, row.map_r, row.map_g, row.map_b),
        )
        for state in row.states:
            if state not in valid_sr:
                log.warn(
                    f"strategic_region {row.region} state {state}：不在 state_regions，已跳过"
                )
                continue
            conn.execute(
                "INSERT INTO ref_strat_st (region, state) VALUES (?, ?)",
                (row.region, state),
            )

    _progress("本地化文本")
    for locale in SUPPORTED_LOCALES:
        for row in parse_localization_merged(
            mod_root, vanilla, locale=locale, replace_paths=replace_paths
        ):
            conn.execute(
                "INSERT INTO ref_loc (loc_key, locale, text) VALUES (?, ?, ?)",
                (row.key, locale, row.text),
            )
    _fill_religion_names(conn)


def _insert_map_assets(
    conn: sqlite3.Connection,
    mod_root: Path,
    vanilla: Path,
    *,
    on_static_layer_progress: Callable[[str, int, int], None] | None = None,
) -> None:
    _progress("省份地图")
    png_path, png_bytes = resolve_provinces_png(mod_root, vanilla)
    conn.execute(
        "INSERT INTO map_png (id, source_path, png) VALUES (1, ?, ?)",
        (str(png_path), png_bytes),
    )
    _insert_static_map_layers(
        conn, on_layer_progress=on_static_layer_progress
    )


def _fill_religion_names(conn: sqlite3.Connection) -> None:
    for locale, column in (("zh", "name_zh"), ("en", "name_en")):
        conn.execute(
            f"""
            UPDATE ref_religion
            SET {column} = COALESCE(
                (
                    SELECT text FROM ref_loc
                    WHERE loc_key = ref_religion.religion AND locale = ?
                ),
                ''
            )
            """,
            (locale,),
        )


def _insert_static_map_layers(
    conn: sqlite3.Connection,
    *,
    on_layer_progress=None,
) -> None:
    _progress("静态地图图层")
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from interactive_map.precompute_layers import insert_static_assets  # noqa: WPS433

    insert_static_assets(conn, on_layer_progress=on_layer_progress)


def _insert_edit(
    conn: sqlite3.Connection,
    mod_root: Path,
    vanilla: Path,
    log: ImportLog,
    replace_paths: frozenset[str],
) -> None:
    _progress("开局州历史")
    meta_rows, ownership_rows = load_history_states(
        mod_root, vanilla, replace_paths, log=log
    )
    if not log.ok:
        return
    ownership_rows = _merge_ownership_rows(ownership_rows, log)
    _progress("开局人口")
    pops = load_history_pops(mod_root, vanilla, replace_paths)
    _progress("开局建筑")
    sites = load_history_buildings(mod_root, vanilla, replace_paths)

    valid_tags = {r[0] for r in conn.execute("SELECT tag FROM ref_tag")}
    valid_cultures = {r[0] for r in conn.execute("SELECT culture FROM ref_culture")}
    valid_buildings = {r[0] for r in conn.execute("SELECT building FROM ref_bld")}
    valid_states = {r[0] for r in conn.execute("SELECT state FROM ref_sr")}

    pm_by_pmg = _pm_index(conn)
    building_pmgs = _building_pmgs(conn)

    for row in meta_rows:
        if row.state not in valid_states:
            log.warn(f"state_meta {row.state}：不在 state_regions，已跳过")
            continue
        conn.execute("INSERT OR IGNORE INTO geo_state (state) VALUES (?)", (row.state,))
        seen_homelands: set[str] = set()
        for culture in row.homelands:
            if culture not in valid_cultures:
                log.warn(f"{row.state} homeland {culture}：不在文化白名单，已删除")
                continue
            if culture in seen_homelands:
                log.warn(f"{row.state} homeland {culture}：重复，已忽略")
                continue
            seen_homelands.add(culture)
            conn.execute(
                "INSERT INTO geo_homeland (state, culture) VALUES (?, ?)",
                (row.state, culture),
            )
        seen_claims: set[str] = set()
        for claim in row.claims:
            if claim not in valid_tags:
                log.warn(f"{row.state} claim {claim}：不在 tag 白名单，已删除")
                continue
            if claim in seen_claims:
                log.warn(f"{row.state} claim {claim}：重复，已忽略")
                continue
            seen_claims.add(claim)
            conn.execute(
                "INSERT INTO geo_claim (state, claim_tag) VALUES (?, ?)",
                (row.state, claim),
            )

    province_to_state = {
        str(province): str(state)
        for province, state in conn.execute("SELECT province, state FROM ref_sr_prov")
    }
    st_rows, province_owners = resolve_clean_province_owners(
        ownership_rows,
        province_to_state,
        valid_tags,
        valid_states,
        log,
    )
    st_keys = _insert_st_and_province_owners(conn, st_rows, province_owners)

    pop_keys = {(p.state, p.tag) for p in pops}
    for key in pop_keys - st_keys:
        log.warn(f"pops {key[0]}/{key[1]}：在 states 中不存在对应 tag__state")

    pop_by_key: dict[tuple[str, str, str, str | None, bool], PopRow] = {}
    for pop in pops:
        if pop.tag not in valid_tags:
            log.error(f"pop {pop.state}/{pop.tag}：未定义的 tag")
            continue
        if (pop.state, pop.tag) not in st_keys:
            continue
        if pop.culture not in valid_cultures:
            log.warn(f"pop {pop.state}/{pop.tag} culture {pop.culture}：未知文化，已跳过")
            continue
        if pop.religion is not None:
            exists = conn.execute(
                "SELECT 1 FROM ref_religion WHERE religion = ?", (pop.religion,)
            ).fetchone()
            if not exists:
                log.warn(
                    f"pop {pop.state}/{pop.tag} religion {pop.religion}：未知宗教，已清空"
                )
                pop = PopRow(
                    state=pop.state,
                    tag=pop.tag,
                    culture=pop.culture,
                    religion=None,
                    is_slaves=pop.is_slaves,
                    size=pop.size,
                )
        key = (pop.state, pop.tag, pop.culture, pop.religion, pop.is_slaves)
        if key in pop_by_key:
            prev = pop_by_key[key]
            log.warn(
                f"pop {pop.state}/{pop.tag} culture {pop.culture} "
                f"religion {pop.religion or ''} is_slaves={int(pop.is_slaves)}："
                f"重复人口，已累加 size {prev.size}+{pop.size}={prev.size + pop.size}"
            )
            pop_by_key[key] = PopRow(
                state=pop.state,
                tag=pop.tag,
                culture=pop.culture,
                religion=pop.religion,
                is_slaves=pop.is_slaves,
                size=prev.size + pop.size,
            )
        else:
            pop_by_key[key] = pop

    for pop in pop_by_key.values():
        if pop.size < 1:
            log.warn(
                f"pop {pop.state}/{pop.tag} culture {pop.culture} "
                f"religion {pop.religion or ''} is_slaves={int(pop.is_slaves)}："
                f"size={pop.size} 小于 1，已跳过"
            )
            continue
        conn.execute(
            """
            INSERT INTO st_pop (state, tag, culture, religion, is_slaves, size)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pop.state,
                pop.tag,
                pop.culture,
                pop.religion,
                int(pop.is_slaves),
                pop.size,
            ),
        )

    building_pm_seen: dict[tuple[str, str, str], list[str]] = {}
    for site in sites:
        if site.tag not in valid_tags:
            log.error(f"building {site.state}/{site.tag}：未定义的 tag")
            continue
        if (site.state, site.tag) not in st_keys:
            log.warn(f"building {site.state}/{site.tag}：states 中无对应条目，已跳过")
            continue
        if site.building not in valid_buildings:
            log.warn(f"building {site.state}/{site.tag}：未知建筑 {site.building}，已跳过")
            continue
        if site.reserves != 1:
            log.warn(
                f"building {site.state}/{site.tag}/{site.building}：reserves={site.reserves}（非 1）"
            )
        pm_list = normalize_site_pms(site, pm_by_pmg, building_pmgs, log)
        warn_duplicate_building_pm_mismatch(site, pm_list, building_pm_seen, log)
        cur = conn.execute(
            """
            INSERT INTO st_bld (state, tag, building, reserves)
            VALUES (?, ?, ?, ?)
            """,
            (site.state, site.tag, site.building, site.reserves),
        )
        bld_id = cur.lastrowid
        for ord_, sl in enumerate(site.ownerships):
            conn.execute(
                """
                INSERT INTO st_bld_own (bld_id, ord, ownership, level, owner_tag, owner_state)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    bld_id,
                    ord_,
                    sl.ownership,
                    sl.level,
                    sl.owner_tag,
                    sl.owner_state,
                ),
            )
        for ord_, pm in enumerate(pm_list):
            conn.execute(
                "INSERT INTO st_bld_pm (bld_id, ord, pm) VALUES (?, ?, ?)",
                (bld_id, ord_, pm),
            )

    _progress("地块归属校验")
    _check_unowned_land_provinces(conn, log)
    _validate_st_prov_integrity(conn, log)


def _check_unowned_land_provinces(conn: sqlite3.Connection, log: ImportLog) -> None:
    """Assign orphan provinces within partially claimed states; error on empty land states.

    A land state from map_data must have at least one province claimed by some tag.
    Individual unclaimed provinces inside an otherwise claimed state are assigned
    to the lexicographically greatest tag already present in that state (with warn).
    """
    land_by_state: dict[str, list[str]] = {}
    for state, province, sr_id in conn.execute(
        """
        SELECT sr.state, p.province, sr.sr_id
        FROM ref_sr_prov p
        JOIN ref_sr sr ON sr.state = p.state
        ORDER BY sr.state, p.province
        """
    ):
        if sr_id >= SEA_STATE_ID_MIN:
            continue
        land_by_state.setdefault(str(state), []).append(str(province))

    owned_by_state: dict[str, set[str]] = {}
    tags_by_state: dict[str, set[str]] = {}
    for state, tag, province in conn.execute(
        "SELECT state, tag, province FROM st_prov"
    ):
        state = str(state)
        owned_by_state.setdefault(state, set()).add(str(province))
        tags_by_state.setdefault(state, set()).add(str(tag))

    for state, provinces in land_by_state.items():
        owned = owned_by_state.get(state, set())
        if not owned:
            log.error(f"陆地州 {state} 未被任何 tag 拥有")
            continue

        unowned = [prov for prov in provinces if prov not in owned]
        if not unowned:
            continue

        assign_tag = max(tags_by_state[state])
        for province in unowned:
            if conn.execute(
                "SELECT 1 FROM st_prov WHERE province = ?",
                (province,),
            ).fetchone():
                log.warn(
                    f"province {province}（{state}）未被本州认领，"
                    f"但已被其他 scope 占用，已跳过"
                )
                continue
            log.warn(
                f"province {province}（{state}）未被认领，已分配给 {assign_tag}"
            )
            conn.execute(
                "INSERT INTO st_prov (province, state, tag) VALUES (?, ?, ?)",
                (province, state, assign_tag),
            )


def build_map_db(
    mod_root: Path,
    output: Path,
    config: MapEditorConfig,
    *,
    fail_on_error: bool = True,
    skip_map_images: bool = False,
    on_static_layer_progress: Callable[[str, int, int], None] | None = None,
    on_build_progress: Callable[[int, int, str], None] | None = None,
) -> ImportLog:
    mod_root = mod_root.resolve()
    vanilla = config.vanilla.resolve()
    replace_paths = mod_replace_paths(mod_root)
    output = resolve_build_output_path(output, skip_map_images=skip_map_images)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = _building_db_path(output)
    log = ImportLog()

    _remove_db_files(tmp)

    text_stage = [0]

    def on_text_stage(label: str) -> None:
        text_stage[0] += 1
        if on_build_progress is not None:
            on_build_progress(
                text_stage[0],
                BUILD_TOTAL_STAGES,
                f"正在阅读{label}信息",
            )

    def on_combined_static_progress(label_zh: str, done: int, total: int) -> None:
        if on_static_layer_progress is not None:
            on_static_layer_progress(label_zh, done, total)
        if on_build_progress is not None:
            on_build_progress(
                BUILD_TEXT_STAGE_COUNT + done,
                BUILD_TEXT_STAGE_COUNT + total,
                f"正在绘制{label_zh}图片",
            )

    global _progress_callback
    previous_progress_callback = _progress_callback
    _progress_callback = on_text_stage

    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("built_at", datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("mod_root", str(mod_root)),
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            ("vanilla", str(vanilla)),
        )
        if skip_map_images:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                ("build_mode", "test"),
            )

        _insert_ref_catalogs(
            conn,
            mod_root,
            vanilla,
            log,
            replace_paths,
        )
        _insert_edit(conn, mod_root, vanilla, log, replace_paths)
        if log.ok:
            _progress("历史文件索引")
            all_states = [r[0] for r in conn.execute("SELECT state FROM ref_sr ORDER BY state")]
            insert_history_index(conn, mod_root, vanilla, replace_paths, all_states)
        if not skip_map_images and (log.ok or not fail_on_error):
            _insert_map_assets(
                conn,
                mod_root,
                vanilla,
                on_static_layer_progress=on_combined_static_progress,
            )
        log.persist(conn)
        conn.commit()
    except Exception:
        _remove_db_files(tmp)
        raise
    finally:
        _progress_callback = previous_progress_callback
        conn.close()

    if not log.ok and fail_on_error:
        _remove_db_files(tmp)
        raise BuildMapDbError(log)

    _finalize_db_build(tmp, output)
    from interactive_map.db_snapshot import create_initial_snapshot  # noqa: WPS433

    create_initial_snapshot(output)
    return log
