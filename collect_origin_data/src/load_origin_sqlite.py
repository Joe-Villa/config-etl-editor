"""Build origin.sqlite from collected flat rows (source of truth, not Excel)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from state_region_flat import FlatStateRegion

if TYPE_CHECKING:
    from building_flat import FlatBuilding
    from country_definitions_flat import CountryDefinitionRow
    from history_countries_tech_flat import CountryTechRow
    from history_states_flat import StateMetaRow, StateOwnershipRow
    from market_subordination import MarketSubordinationRow
    from named_colors_flat import NamedColorRow

SCHEMA_PATH = Path(__file__).resolve().parent / "origin_schema.sql"


def _warn_skip(message: str) -> None:
    print(f"  警告：{message}；已跳过")


def _state_region_create_sql(resource_columns: list[str]) -> str:
    resource_defs = "\n".join(
        f"    {col} INTEGER NOT NULL DEFAULT 0," for col in resource_columns
    )
    return f"""
CREATE TABLE state_region (
    id INTEGER NOT NULL PRIMARY KEY,
    state TEXT NOT NULL UNIQUE,
    coastal INTEGER NOT NULL CHECK (coastal IN (0, 1)),
    provinces TEXT NOT NULL,
    prime_land TEXT NOT NULL,
    impassable TEXT NOT NULL,
    arable_land INTEGER NOT NULL,
    arable_resources TEXT NOT NULL,
    city TEXT NOT NULL DEFAULT '',
    port TEXT NOT NULL DEFAULT '',
    farm TEXT NOT NULL DEFAULT '',
    mine TEXT NOT NULL DEFAULT '',
    wood TEXT NOT NULL DEFAULT '',
    city_name TEXT NOT NULL DEFAULT '',
    port_name TEXT NOT NULL DEFAULT '',
    farm_name TEXT NOT NULL DEFAULT '',
    mine_name TEXT NOT NULL DEFAULT '',
    wood_name TEXT NOT NULL DEFAULT '',
{resource_defs}
    CHECK (state GLOB 'STATE_*')
);
"""


def _create_tables(conn: sqlite3.Connection, resource_columns: list[str]) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.execute(_state_region_create_sql(resource_columns))
    conn.executescript(
        """
CREATE TABLE state (
    state TEXT NOT NULL PRIMARY KEY,
    FOREIGN KEY (state) REFERENCES state_region (state)
);

CREATE TABLE state_meta (
    state TEXT NOT NULL PRIMARY KEY,
    homelands TEXT NOT NULL DEFAULT '',
    claims TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (state) REFERENCES state (state)
);

CREATE TABLE named_color (
    color_key TEXT NOT NULL PRIMARY KEY,
    r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
    g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
    b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255)
);

CREATE TABLE country_definition (
    tag TEXT NOT NULL PRIMARY KEY,
    r INTEGER NOT NULL CHECK (r BETWEEN 0 AND 255),
    g INTEGER NOT NULL CHECK (g BETWEEN 0 AND 255),
    b INTEGER NOT NULL CHECK (b BETWEEN 0 AND 255)
);

CREATE TABLE tag (
    tag TEXT NOT NULL PRIMARY KEY,
    FOREIGN KEY (tag) REFERENCES country_definition (tag)
);

CREATE TABLE tag__state (
    tag TEXT NOT NULL,
    state TEXT NOT NULL,
    owned_provinces TEXT NOT NULL DEFAULT '',
    state_type TEXT NOT NULL DEFAULT 'incorporated',
    population INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tag, state),
    FOREIGN KEY (tag) REFERENCES tag (tag),
    FOREIGN KEY (state) REFERENCES state (state)
);

CREATE TABLE tag__market_master (
    tag TEXT NOT NULL PRIMARY KEY,
    market_master TEXT NOT NULL,
    FOREIGN KEY (tag) REFERENCES tag (tag),
    FOREIGN KEY (market_master) REFERENCES tag (tag)
);

CREATE TABLE tag__technology (
    tag TEXT NOT NULL PRIMARY KEY,
    technologies TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (tag) REFERENCES tag (tag)
);

CREATE TABLE tag__state__building (
    tag TEXT NOT NULL,
    state TEXT NOT NULL,
    building TEXT NOT NULL,
    id INTEGER NOT NULL DEFAULT 0,
    level INTEGER NOT NULL,
    pm TEXT NOT NULL DEFAULT '[]',
    ownership TEXT NOT NULL,
    owner_tag TEXT NOT NULL DEFAULT '',
    owner_state TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (tag, state, building, ownership, owner_tag, owner_state),
    FOREIGN KEY (tag, state) REFERENCES tag__state (tag, state)
);
"""
    )


def _insert_state_regions(
    conn: sqlite3.Connection,
    rows: list[FlatStateRegion],
    resource_columns: list[str],
) -> None:
    headers = [
        "id",
        "state",
        "coastal",
        "provinces",
        "prime_land",
        "impassable",
        "arable_land",
        "arable_resources",
        "city",
        "port",
        "farm",
        "mine",
        "wood",
        "city_name",
        "port_name",
        "farm_name",
        "mine_name",
        "wood_name",
        *resource_columns,
    ]
    placeholders = ", ".join("?" for _ in headers)
    sql = f"INSERT INTO state_region ({', '.join(headers)}) VALUES ({placeholders})"
    from state_region_flat import row_to_list

    for row in rows:
        try:
            conn.execute(sql, row_to_list(row, resource_columns))
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"state_region {row.state}：{exc}")


def _insert_states(conn: sqlite3.Connection, rows: list[FlatStateRegion]) -> None:
    for row in rows:
        try:
            conn.execute("INSERT INTO state (state) VALUES (?)", (row.state,))
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"state {row.state}：{exc}")


def _insert_state_meta(
    conn: sqlite3.Connection,
    rows: list[StateMetaRow],
    valid_states: set[str],
) -> None:
    from history_states_flat import _join_csv

    for row in rows:
        if row.state not in valid_states:
            _warn_skip(f"state_meta {row.state}：对应 state 不在 state_region 中")
            continue
        try:
            conn.execute(
                "INSERT INTO state_meta (state, homelands, claims) VALUES (?, ?, ?)",
                (row.state, _join_csv(row.homelands), _join_csv(row.claims)),
            )
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"state_meta {row.state}：{exc}")


def _insert_named_colors(
    conn: sqlite3.Connection,
    rows: list[NamedColorRow],
) -> None:
    for row in rows:
        try:
            conn.execute(
                "INSERT INTO named_color (color_key, r, g, b) VALUES (?, ?, ?, ?)",
                (row.key, row.r, row.g, row.b),
            )
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"named_color {row.key}：{exc}")


def _insert_country_definitions(
    conn: sqlite3.Connection,
    rows: list[CountryDefinitionRow],
) -> set[str]:
    inserted: set[str] = set()
    for row in rows:
        try:
            conn.execute(
                "INSERT INTO country_definition (tag, r, g, b) VALUES (?, ?, ?, ?)",
                (row.tag, row.r, row.g, row.b),
            )
            inserted.add(row.tag)
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"country_definition {row.tag}：{exc}")
    return inserted


def _insert_tags(conn: sqlite3.Connection, tags: list[str]) -> set[str]:
    inserted: set[str] = set()
    for tag in tags:
        if not tag:
            _warn_skip("tag：标签为空")
            continue
        try:
            conn.execute("INSERT INTO tag (tag) VALUES (?)", (tag,))
            inserted.add(tag)
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"tag {tag}：{exc}")
    return inserted


def _insert_tag__state(
    conn: sqlite3.Connection,
    rows: list[StateOwnershipRow],
    valid_states: set[str],
    valid_tags: set[str],
) -> set[tuple[str, str]]:
    from history_states_flat import _join_csv

    inserted: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.tag, row.state)
        if not row.tag:
            _warn_skip(f"ownership（{row.state}）：标签为空")
            continue
        if row.tag not in valid_tags:
            _warn_skip(f"ownership {key}：tag 未注册")
            continue
        if row.state not in valid_states:
            _warn_skip(f"ownership {key}：state 不在 state_region 中")
            continue
        try:
            conn.execute(
                """
                INSERT INTO tag__state (
                    tag, state, owned_provinces, state_type, population
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    row.tag,
                    row.state,
                    _join_csv(row.owned_provinces),
                    row.state_type,
                    row.population,
                ),
            )
            inserted.add(key)
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"ownership {key}：{exc}")
    return inserted


def _insert_market_master(
    conn: sqlite3.Connection,
    rows: list[MarketSubordinationRow],
    valid_tags: set[str],
) -> None:
    for row in rows:
        if row.tag not in valid_tags:
            _warn_skip(
                f"market_subordination 属国 {row.tag}：不在开局活跃国家中"
            )
            continue
        if row.market_master not in valid_tags:
            _warn_skip(
                f"market_subordination {row.tag}："
                f"宗主 market_master {row.market_master} 不在开局活跃国家中"
            )
            continue
        try:
            conn.execute(
                "INSERT INTO tag__market_master (tag, market_master) VALUES (?, ?)",
                (row.tag, row.market_master),
            )
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"market_subordination {row.tag}：{exc}")


def _insert_technologies(
    conn: sqlite3.Connection,
    rows: list[CountryTechRow],
    valid_tags: set[str],
) -> None:
    for row in rows:
        if row.tag not in valid_tags:
            _warn_skip(f"tag__technology {row.tag}：不在开局活跃国家中")
            continue
        try:
            conn.execute(
                "INSERT INTO tag__technology (tag, technologies) VALUES (?, ?)",
                (row.tag, row.technologies_csv),
            )
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"tag__technology {row.tag}：{exc}")


def _insert_buildings(
    conn: sqlite3.Connection,
    rows: list[FlatBuilding],
    valid_tag__state: set[tuple[str, str]],
) -> None:
    from building_flat import merge_building_rows

    for row in merge_building_rows(rows, on_warn=_warn_skip):
        tag = row.country
        key = (tag, row.state, row.name)
        if not tag:
            _warn_skip(f"building {row.state}/{row.name}：标签为空")
            continue
        if (tag, row.state) not in valid_tag__state:
            _warn_skip(f"building {key}：(tag, state) 不在 tag__state 中")
            continue
        try:
            conn.execute(
                """
                INSERT INTO tag__state__building (
                    tag, state, building, id, level, pm, ownership, owner_tag, owner_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tag,
                    row.state,
                    row.name,
                    row.id,
                    row.level,
                    json.dumps(row.pm, ensure_ascii=False),
                    row.ownership,
                    row.owner_tag,
                    row.owner_state,
                ),
            )
        except sqlite3.IntegrityError as exc:
            _warn_skip(f"building {key}：{exc}")


def build_origin_database(
    db_path: Path,
    *,
    region_rows: list[FlatStateRegion],
    meta_rows: list[StateMetaRow],
    own_rows: list[StateOwnershipRow],
    market_rows: list[MarketSubordinationRow],
    country_tech_rows: list[CountryTechRow],
    country_definition_rows: list[CountryDefinitionRow],
    named_color_rows: list[NamedColorRow],
    building_rows: list[FlatBuilding],
    resource_columns: list[str],
) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    _create_tables(conn, resource_columns)

    valid_states = {row.state for row in region_rows}
    _insert_state_regions(conn, region_rows, resource_columns)
    _insert_states(conn, region_rows)
    _insert_state_meta(conn, meta_rows, valid_states)

    from country_definitions_flat import validate_active_tags_have_definitions

    active_tags = sorted({row.tag for row in own_rows if row.tag})
    validate_active_tags_have_definitions(set(active_tags), country_definition_rows)
    _insert_named_colors(conn, named_color_rows)
    _insert_country_definitions(conn, country_definition_rows)
    valid_tags = _insert_tags(conn, active_tags)
    inserted_tag__state = _insert_tag__state(conn, own_rows, valid_states, valid_tags)

    _insert_market_master(conn, market_rows, valid_tags)
    _insert_technologies(conn, country_tech_rows, valid_tags)
    _insert_buildings(conn, building_rows, inserted_tag__state)

    conn.commit()
    return conn


def print_stats(conn: sqlite3.Connection) -> None:
    tables = [
        "state_region",
        "state",
        "state_meta",
        "country_definition",
        "named_color",
        "tag",
        "tag__state",
        "tag__market_master",
        "tag__technology",
        "tag__state__building",
    ]
    for name in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"  {name}: {count}")
