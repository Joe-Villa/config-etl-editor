"""Collect origin.sqlite from a Victoria 3 mod directory."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from building_flat import assign_ids, parse_history_buildings_dir
from constants import (
    DATA_DIR,
    METADATA_JSON,
    ORIGIN_DB,
    REL_BUILDINGS,
    REL_COUNTRIES,
    REL_COUNTRY_DEFINITIONS,
    REL_NAMED_COLORS,
    REL_DIPLOMACY,
    REL_POPS,
    REL_POWER_BLOCS,
    REL_STATE_REGIONS,
    REL_STATES,
    RESOURCE_COLUMNS,
)
from config import CollectConfig, load_config
from content_policy import ContentPolicy
from country_definitions_flat import parse_country_definitions_paths
from named_colors_flat import build_named_color_lookup, parse_named_colors_paths
from game_content_resolver import (
    ContentSource,
    load_mod_replace_paths,
    resolve_merged_content,
)
from history_countries_tech_flat import (
    filter_by_ownership as filter_countries_tech_by_ownership,
    parse_countries_paths,
)
from history_pops_flat import parse_pops_dir
from history_states_flat import merge_population_into_ownership, parse_states_dir
from load_origin_sqlite import build_origin_database
from market_subordination import parse_market_subordination_dirs
from state_region_flat import parse_state_regions_dir


@dataclass(frozen=True)
class TableInputSource:
    relative_path: str
    source: ContentSource
    content_dir: Path


@dataclass(frozen=True)
class ExportResult:
    name: str
    path: Path
    rows: int
    source: ContentSource
    relative_path: str
    content_dir: Path
    inputs: dict[str, TableInputSource] = field(default_factory=dict)
    derived_from: tuple[str, ...] = ()
    forced_vanilla: bool = False


@dataclass(frozen=True)
class CollectSummary:
    run_id: str
    mod_root: Path
    output_dir: Path
    vanilla_game: Path
    metadata_path: Path
    results: tuple[ExportResult, ...]
    content_policy: ContentPolicy = field(default_factory=ContentPolicy)
    config: CollectConfig | None = None


def derive_output_dir_name(mod_root: Path) -> str:
    """Use the last path segment as the output folder name (e.g. .../3346844497 → 3346844497)."""
    name = mod_root.resolve().name
    if not name:
        raise ValueError(f"无法从路径推导输出目录名：{mod_root}")
    return name


def _prepare_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)


def _resolve_merged_content(
    mod_root: Path,
    relative: str,
    vanilla_game: Path,
    policy: ContentPolicy,
    replace_paths: frozenset[str],
):
    force = not policy.uses_mod(relative)
    merged = resolve_merged_content(
        mod_root,
        relative,
        vanilla_game,
        force_vanilla=force,
        replace_paths=replace_paths,
    )
    mod_would_apply = merged.source in (ContentSource.MOD, ContentSource.MOD_PART)
    forced = force and mod_would_apply
    return merged, forced


def collect(
    mod_root: Path,
    *,
    run_id: str | None = None,
    config: CollectConfig | None = None,
) -> CollectSummary:
    config = config or load_config()
    mod_root = mod_root.resolve()
    vanilla_game = config.vanilla.resolve()
    if not mod_root.is_dir():
        raise FileNotFoundError(f"模组根目录不存在：{mod_root}")
    if not vanilla_game.is_dir():
        raise FileNotFoundError(f"原版游戏目录不存在：{vanilla_game}")

    run_id = run_id or derive_output_dir_name(mod_root)
    policy = config.content_policy()
    replace_paths = load_mod_replace_paths(mod_root)
    output_dir = (DATA_DIR / run_id).resolve()
    _prepare_output_dir(output_dir)

    regions_merged, regions_forced = _resolve_merged_content(
        mod_root, REL_STATE_REGIONS, vanilla_game, policy, replace_paths
    )
    region_rows = parse_state_regions_dir(
        paths=regions_merged.paths,
        mod_dir=regions_merged.mod_dir,
        resource_columns=RESOURCE_COLUMNS,
    )
    from hub_localization import apply_hub_names_to_regions, default_hub_names_path, load_hub_names

    hub_names_path = default_hub_names_path(vanilla_game)
    if hub_names_path.is_file():
        apply_hub_names_to_regions(region_rows, load_hub_names(hub_names_path))

    pops_merged, pops_forced = _resolve_merged_content(
        mod_root, REL_POPS, vanilla_game, policy, replace_paths
    )
    pop_rows = parse_pops_dir(
        paths=pops_merged.paths,
        mod_dir=pops_merged.mod_dir,
        skip_example=False,
    )

    diplomacy_merged, diplomacy_forced = _resolve_merged_content(
        mod_root, REL_DIPLOMACY, vanilla_game, policy, replace_paths
    )
    blocs_merged, blocs_forced = _resolve_merged_content(
        mod_root, REL_POWER_BLOCS, vanilla_game, policy, replace_paths
    )
    market_source = _combine_sources(diplomacy_merged.source, blocs_merged.source)
    market_rows, _own_market = parse_market_subordination_dirs(
        diplomacy_paths=diplomacy_merged.paths,
        power_blocs_paths=blocs_merged.paths,
        diplomacy_mod_dir=diplomacy_merged.mod_dir,
        power_blocs_mod_dir=blocs_merged.mod_dir,
    )

    states_merged, states_forced = _resolve_merged_content(
        mod_root, REL_STATES, vanilla_game, policy, replace_paths
    )
    meta_rows, own_rows = parse_states_dir(
        paths=states_merged.paths,
        mod_dir=states_merged.mod_dir,
    )
    own_rows = merge_population_into_ownership(own_rows, pop_rows)
    states_source = _combine_sources(states_merged.source, pops_merged.source)

    buildings_merged, buildings_forced = _resolve_merged_content(
        mod_root, REL_BUILDINGS, vanilla_game, policy, replace_paths
    )
    building_rows = assign_ids(
        parse_history_buildings_dir(paths=buildings_merged.paths)
    )

    countries_merged, countries_forced = _resolve_merged_content(
        mod_root, REL_COUNTRIES, vanilla_game, policy, replace_paths
    )
    country_tech_rows = filter_countries_tech_by_ownership(
        parse_countries_paths(
            countries_merged.paths,
            mod_dir=countries_merged.mod_dir,
        ),
        own_rows,
    )

    country_defs_merged, country_defs_forced = _resolve_merged_content(
        mod_root, REL_COUNTRY_DEFINITIONS, vanilla_game, policy, replace_paths
    )
    named_colors_merged, named_colors_forced = _resolve_merged_content(
        mod_root, REL_NAMED_COLORS, vanilla_game, policy, replace_paths
    )
    named_color_rows = parse_named_colors_paths(
        named_colors_merged.paths,
        mod_dir=named_colors_merged.mod_dir,
    )
    named_color_lookup = build_named_color_lookup(named_color_rows)
    country_definition_rows = parse_country_definitions_paths(
        country_defs_merged.paths,
        mod_dir=country_defs_merged.mod_dir,
        named_colors=named_color_lookup,
    )

    origin_db_path = output_dir / ORIGIN_DB
    origin_conn = build_origin_database(
        origin_db_path,
        region_rows=region_rows,
        meta_rows=meta_rows,
        own_rows=own_rows,
        market_rows=market_rows,
        country_tech_rows=country_tech_rows,
        country_definition_rows=country_definition_rows,
        named_color_rows=named_color_rows,
        building_rows=building_rows,
        resource_columns=RESOURCE_COLUMNS,
    )
    origin_table_rows = sum(
        origin_conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        for name in (
            "state_region",
            "state",
            "state_meta",
            "named_color",
            "country_definition",
            "tag",
            "tag__state",
            "tag__market_master",
            "tag__technology",
            "tag__state__building",
        )
    )
    origin_conn.close()

    origin_inputs = {
        "state_regions": TableInputSource(
            REL_STATE_REGIONS,
            regions_merged.source,
            regions_merged.content_dir,
        ),
        "diplomacy": TableInputSource(
            REL_DIPLOMACY,
            diplomacy_merged.source,
            diplomacy_merged.content_dir,
        ),
        "power_blocs": TableInputSource(
            REL_POWER_BLOCS,
            blocs_merged.source,
            blocs_merged.content_dir,
        ),
        "states": TableInputSource(
            REL_STATES,
            states_merged.source,
            states_merged.content_dir,
        ),
        "pops": TableInputSource(
            REL_POPS,
            pops_merged.source,
            pops_merged.content_dir,
        ),
        "buildings": TableInputSource(
            REL_BUILDINGS,
            buildings_merged.source,
            buildings_merged.content_dir,
        ),
        "countries": TableInputSource(
            REL_COUNTRIES,
            countries_merged.source,
            countries_merged.content_dir,
        ),
        "country_definitions": TableInputSource(
            REL_COUNTRY_DEFINITIONS,
            country_defs_merged.source,
            country_defs_merged.content_dir,
        ),
    }
    origin_forced = any(
        flag
        for flag in (
            regions_forced,
            diplomacy_forced,
            blocs_forced,
            states_forced,
            pops_forced,
            buildings_forced,
            countries_forced,
            country_defs_forced,
        )
    )

    results: tuple[ExportResult, ...] = (
        ExportResult(
            name="origin",
            path=origin_db_path,
            rows=origin_table_rows,
            source=_combine_sources(
                regions_merged.source,
                market_source,
                states_source,
                buildings_merged.source,
                countries_merged.source,
                country_defs_merged.source,
            ),
            relative_path="",
            content_dir=origin_db_path.parent,
            inputs=origin_inputs,
            forced_vanilla=origin_forced,
        ),
    )

    summary = CollectSummary(
        run_id=run_id,
        mod_root=mod_root,
        output_dir=output_dir,
        vanilla_game=vanilla_game,
        metadata_path=output_dir / METADATA_JSON,
        results=results,
        content_policy=policy,
        config=config,
    )
    _write_metadata(summary)
    return summary


def append_results_to_metadata(
    summary: CollectSummary,
    extra_results: tuple[ExportResult, ...],
) -> CollectSummary:
    merged = CollectSummary(
        run_id=summary.run_id,
        mod_root=summary.mod_root,
        output_dir=summary.output_dir,
        vanilla_game=summary.vanilla_game,
        metadata_path=summary.metadata_path,
        results=summary.results + extra_results,
        content_policy=summary.content_policy,
        config=summary.config,
    )
    _write_metadata(merged)
    return merged


def _input_to_dict(item: TableInputSource, *, hide_full_path: bool) -> dict[str, str]:
    payload: dict[str, str] = {
        "relative_path": item.relative_path,
        "source": item.source.value,
    }
    if not hide_full_path:
        payload["content_dir"] = str(item.content_dir)
    return payload


def _write_metadata(summary: CollectSummary) -> None:
    hide_full_path = bool(summary.config and summary.config.metadata_hide_full_path)
    tables: dict[str, dict] = {}
    for result in summary.results:
        try:
            rel_file = result.path.relative_to(summary.output_dir).as_posix()
        except ValueError:
            rel_file = result.path.as_posix()
        entry: dict = {
            "file": rel_file,
            "source": result.source.value,
            "rows": result.rows,
        }
        if result.derived_from:
            entry["derived_from"] = list(result.derived_from)
        else:
            entry["relative_path"] = result.relative_path
            if result.forced_vanilla:
                entry["forced_vanilla"] = True
            if result.inputs:
                entry["inputs"] = {
                    key: _input_to_dict(value, hide_full_path=hide_full_path)
                    for key, value in result.inputs.items()
                }
            elif not hide_full_path:
                entry["content_dir"] = str(result.content_dir)
        tables[result.name] = entry

    payload: dict = {
        "run_id": summary.run_id,
        "content_policy": summary.content_policy.to_dict(),
        "source_legend": {
            "vanilla": "模组目录无 txt 文件，全部使用原版 game",
            "mod": "模组覆盖原版该路径下全部同名 txt 文件（含空文件）",
            "mod_part": "模组仅覆盖部分同名 txt，其余取自原版",
            "derived": "由 origin.sqlite 聚合计算生成",
        },
        "tables": tables,
    }
    if not hide_full_path:
        payload["mod_root"] = str(summary.mod_root)
        payload["vanilla_game"] = str(summary.vanilla_game)
        payload["output_dir"] = str(summary.output_dir)
    summary.metadata_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _combine_sources(*sources: ContentSource) -> ContentSource:
    unique = set(sources)
    if unique == {ContentSource.VANILLA}:
        return ContentSource.VANILLA
    if unique == {ContentSource.MOD}:
        return ContentSource.MOD
    return ContentSource.MOD_PART
