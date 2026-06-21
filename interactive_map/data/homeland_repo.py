"""Homeland tables — SQL only."""

from __future__ import annotations

from collections import defaultdict

from interactive_map.data.sql_session import SqlSession


def load_state_culture_rows(sql: SqlSession) -> list[tuple[str, str]]:
    return [
        (str(state), str(culture))
        for state, culture in sql.fetchall(
            "SELECT state, culture FROM geo_homeland ORDER BY state, culture"
        )
    ]


def load_state_cultures_map(sql: SqlSession) -> dict[str, list[str]]:
    by_state: dict[str, list[str]] = defaultdict(list)
    for state, culture in load_state_culture_rows(sql):
        by_state[state].append(culture)
    return dict(by_state)


def load_all_geo_states(sql: SqlSession) -> set[str]:
    return {str(row[0]) for row in sql.fetchall("SELECT state FROM geo_state")}
