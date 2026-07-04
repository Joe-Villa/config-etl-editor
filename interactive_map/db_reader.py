"""Read map-relevant data from map_editor.sqlite only.

Interactive map export must not read game files, other sqlite DBs, or config paths.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from interactive_map.png_util import png_size, province_hex_to_key

# Vic3 map_data/state_regions/99_seas.txt — sr_id >= 3000 are sea state regions
SEA_STATE_ID_MIN = 3000

_HUB_LOC_RE = re.compile(r"^HUB_NAME_(STATE_\w+)_(city|port|farm|mine|wood)$")


def load_provinces_png_bytes(conn: sqlite3.Connection) -> bytes:
    row = conn.execute("SELECT png FROM map_png WHERE id = 1").fetchone()
    if row is None:
        raise ValueError("数据库缺少 map_png 记录")
    return row[0]


def load_layer_png_bytes(conn: sqlite3.Connection, layer: str) -> bytes | None:
    try:
        row = conn.execute(
            "SELECT png FROM map_layer_png WHERE layer = ?", (layer,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return row[0]


def load_province_tag_state(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    mapping: dict[int, tuple[str, str]] = {}
    for tag, state, province in conn.execute(
        "SELECT tag, state, province FROM st_prov ORDER BY tag, state, province"
    ):
        mapping[province_hex_to_key(str(province))] = (str(tag), str(state))
    return mapping


def load_provinces_in_scope(
    conn: sqlite3.Connection,
    tag: str,
    state: str,
) -> set[int]:
    return {
        province_hex_to_key(str(province))
        for (province,) in conn.execute(
            "SELECT province FROM st_prov WHERE tag = ? AND state = ?",
            (tag, state),
        )
    }


def load_provinces_in_geographic_state(
    conn: sqlite3.Connection,
    state: str,
) -> set[int]:
    return {
        province_hex_to_key(str(province))
        for (province,) in conn.execute(
            "SELECT province FROM ref_sr_prov WHERE state = ?",
            (state,),
        )
    }


def load_provinces_for_tag(conn: sqlite3.Connection, tag: str) -> set[int]:
    return {
        province_hex_to_key(str(province))
        for (province,) in conn.execute(
            "SELECT province FROM st_prov WHERE tag = ?",
            (tag,),
        )
    }


def load_province_geographic_state(conn: sqlite3.Connection) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for state, province in conn.execute(
        "SELECT state, province FROM ref_sr_prov ORDER BY state, province"
    ):
        mapping[province_hex_to_key(str(province))] = str(state)
    return mapping


def load_land_province_keys(conn: sqlite3.Connection) -> set[int]:
    """Provinces belonging to land state regions (excludes sea sr_id >= 3000)."""
    return {
        province_hex_to_key(str(province))
        for (province,) in conn.execute(
            """
            SELECT p.province
            FROM ref_sr_prov p
            JOIN ref_sr sr ON sr.state = p.state
            WHERE sr.sr_id < ?
            """,
            (SEA_STATE_ID_MIN,),
        )
    }


def load_sea_province_keys(conn: sqlite3.Connection) -> set[int]:
    return {
        province_hex_to_key(str(province))
        for (province,) in conn.execute(
            """
            SELECT p.province
            FROM ref_sr_prov p
            JOIN ref_sr sr ON sr.state = p.state
            WHERE sr.sr_id >= ?
            """,
            (SEA_STATE_ID_MIN,),
        )
    }


def load_prime_land_keys(conn: sqlite3.Connection) -> set[int]:
    return {
        province_hex_to_key(str(province))
        for (province,) in conn.execute("SELECT province FROM ref_sr_prime")
    }


def load_impassable_keys(conn: sqlite3.Connection) -> set[int]:
    return {
        province_hex_to_key(str(province))
        for (province,) in conn.execute("SELECT province FROM ref_sr_impassable")
    }


def load_country_colors(conn: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    return {
        str(tag): (int(r), int(g), int(b))
        for tag, r, g, b in conn.execute("SELECT tag, r, g, b FROM ref_tag")
    }


def load_culture_colors(conn: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    return {
        str(culture): (int(r), int(g), int(b))
        for culture, r, g, b in conn.execute(
            "SELECT culture, r, g, b FROM ref_culture ORDER BY culture"
        )
    }


def load_religion_colors(conn: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    try:
        rows = conn.execute(
            "SELECT religion, r, g, b FROM ref_religion ORDER BY religion"
        ).fetchall()
    except sqlite3.OperationalError:
        return {
            str(religion): (255, 255, 255)
            for (religion,) in conn.execute("SELECT religion FROM ref_religion")
        }
    return {
        str(religion): (int(r), int(g), int(b))
        for religion, r, g, b in rows
    }


def load_religions_json(conn: sqlite3.Connection) -> dict[str, dict]:
    return {
        str(religion): {
            "r": int(r),
            "g": int(g),
            "b": int(b),
            "name_zh": str(name_zh or ""),
            "name_en": str(name_en or ""),
        }
        for religion, r, g, b, name_zh, name_en in conn.execute(
            """
            SELECT religion, r, g, b, name_zh, name_en
            FROM ref_religion
            ORDER BY religion
            """
        )
    }


def load_tag_cultures(conn: sqlite3.Connection) -> dict[str, list[str]]:
    by_tag: dict[str, list[str]] = {}
    for tag, culture, _ord in conn.execute(
        "SELECT tag, culture, ord FROM ref_tag_culture ORDER BY tag, ord, culture"
    ):
        by_tag.setdefault(str(tag), []).append(str(culture))
    return by_tag


def load_states_json(conn: sqlite3.Connection) -> dict[str, dict]:
    pop_by_key = {
        (tag, state): int(total or 0)
        for tag, state, total in conn.execute(
            """
            SELECT tag, state, SUM(size)
            FROM st_pop
            GROUP BY tag, state
            """
        )
    }
    out: dict[str, dict] = {}
    for tag, state, state_type in conn.execute(
        "SELECT tag, state, state_type FROM st ORDER BY tag, state"
    ):
        key = f"{tag}::{state}"
        out[key] = {
            "tag": tag,
            "state": state,
            "population": pop_by_key.get((tag, state), 0),
            "state_type": state_type or "incorporated",
        }
    return out


def load_tag_country_types(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(tag): str(country_type or "recognized")
        for tag, country_type in conn.execute(
            "SELECT tag, country_type FROM ref_tag ORDER BY tag"
        )
    }


def load_countries_json(conn: sqlite3.Connection) -> dict[str, dict]:
    tag_cultures = load_tag_cultures(conn)
    return {
        str(tag): {
            "r": int(r),
            "g": int(g),
            "b": int(b),
            "country_type": str(country_type or "recognized"),
            "cultures": tag_cultures.get(str(tag), []),
        }
        for tag, r, g, b, country_type in conn.execute(
            "SELECT tag, r, g, b, country_type FROM ref_tag ORDER BY tag"
        )
    }


def load_cultures_json(conn: sqlite3.Connection) -> dict[str, dict]:
    return {
        str(culture): {"r": int(r), "g": int(g), "b": int(b)}
        for culture, r, g, b in conn.execute(
            "SELECT culture, r, g, b FROM ref_culture ORDER BY culture"
        )
    }


def load_provinces_json(conn: sqlite3.Connection) -> dict[str, dict]:
    from interactive_map.png_util import key_to_hex

    return {
        key_to_hex(key): {"tag": tag, "state": state}
        for key, (tag, state) in load_province_tag_state(conn).items()
    }


def load_loc_dict(conn: sqlite3.Connection, locale: str = "zh") -> dict[str, str]:
    return {
        str(key): str(text)
        for key, text in conn.execute(
            "SELECT loc_key, text FROM ref_loc WHERE locale = ?",
            (locale,),
        )
    }


def load_names_json(
    conn: sqlite3.Connection,
    *,
    loc: dict[str, str] | None = None,
    locale: str = "zh",
) -> dict[str, dict[str, str]]:
    if loc is None:
        loc = load_loc_dict(conn, locale)
    return _names_from_loc(conn, loc)


def build_merged_loc(
    conn: sqlite3.Connection,
    vanilla: Path,
    mod_root: Path | None = None,
    locale: str = "zh",
) -> dict[str, str]:
    """Vanilla+mod 本地化合并，再以 sqlite ref_loc 覆盖（保留模组特有 tag 名等）。"""
    import sys

    root = Path(__file__).resolve().parents[1]
    src = root / "map_db"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from parse_ref import parse_localization_merged  # noqa: WPS433

    mod_root = mod_root or vanilla
    loc = {
        row.key: row.text
        for row in parse_localization_merged(mod_root, vanilla, locale=locale)
    }
    for key, text in conn.execute(
        "SELECT loc_key, text FROM ref_loc WHERE locale = ?",
        (locale,),
    ):
        loc[str(key)] = str(text)
    return loc


def load_names_json_merged(
    conn: sqlite3.Connection,
    vanilla: Path,
    mod_root: Path | None = None,
    *,
    locale: str = "zh",
) -> dict[str, dict[str, str]]:
    return load_names_json(
        conn,
        loc=build_merged_loc(conn, vanilla, mod_root, locale),
    )


def load_names_json_all_locales(
    conn: sqlite3.Connection,
    vanilla: Path | None = None,
    mod_root: Path | None = None,
) -> dict[str, dict[str, dict[str, str]]]:
    """Return names grouped by locale: { en: {...}, zh: {...}, ... }."""
    from parse_ref import SUPPORTED_LOCALES  # noqa: WPS433

    out: dict[str, dict[str, dict[str, str]]] = {}
    for locale in SUPPORTED_LOCALES:
        if vanilla is not None:
            loc = build_merged_loc(conn, vanilla, mod_root, locale)
        else:
            loc = load_loc_dict(conn, locale)
        out[locale] = load_names_json(conn, loc=loc)
    return out


def load_names_json_merged_all_locales(
    conn: sqlite3.Connection,
    vanilla: Path,
    mod_root: Path | None = None,
) -> dict[str, dict[str, dict[str, str]]]:
    return load_names_json_all_locales(conn, vanilla=vanilla, mod_root=mod_root)


def _names_from_loc(
    conn: sqlite3.Connection,
    loc: dict[str, str],
) -> dict[str, dict[str, str]]:
    valid_tags = {str(row[0]) for row in conn.execute("SELECT tag FROM ref_tag")}
    valid_states = {str(row[0]) for row in conn.execute("SELECT state FROM ref_sr")}
    valid_cultures = {str(row[0]) for row in conn.execute("SELECT culture FROM ref_culture")}
    valid_religions = {str(row[0]) for row in conn.execute("SELECT religion FROM ref_religion")}
    valid_buildings = {str(row[0]) for row in conn.execute("SELECT building FROM ref_bld")}
    valid_building_groups = {
        str(row[0]) for row in conn.execute("SELECT building_group FROM ref_bg")
    }
    valid_pms = {str(row[0]) for row in conn.execute("SELECT pm FROM ref_pmg_pm")}
    valid_companies = {str(row[0]) for row in conn.execute("SELECT company_type FROM ref_co")}
    valid_regions = {str(row[0]) for row in conn.execute("SELECT region FROM ref_strat")}
    valid_country_types = {
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT country_type FROM ref_tag WHERE country_type != ''"
        )
    }
    tags: dict[str, str] = {}
    states: dict[str, str] = {}
    hubs: dict[str, str] = {}
    cultures: dict[str, str] = {}
    religions: dict[str, str] = {}
    buildings: dict[str, str] = {}
    building_groups: dict[str, str] = {}
    pms: dict[str, str] = {}
    companies: dict[str, str] = {}
    regions: dict[str, str] = {}
    country_types: dict[str, str] = {}
    for key, text in loc.items():
        key = str(key)
        text = str(text)
        if key in valid_tags:
            tags[key] = text
        elif key in valid_states:
            states[key] = text
        elif key in valid_cultures:
            cultures[key] = text
        elif key in valid_religions:
            religions[key] = text
        elif key in valid_buildings:
            buildings[key] = text
        elif key in valid_building_groups:
            building_groups[key] = text
        elif key in valid_pms:
            pms[key] = text
        elif key in valid_companies:
            companies[key] = text
        elif key in valid_regions:
            regions[key] = text
        else:
            match = _HUB_LOC_RE.match(key)
            if match and match.group(1) in valid_states:
                hubs[f"{match.group(1)}::{match.group(2)}"] = text
    for country_type in valid_country_types:
        if country_type in loc:
            country_types[country_type] = loc[country_type]
    return {
        "tags": tags,
        "states": states,
        "hubs": hubs,
        "cultures": cultures,
        "religions": religions,
        "buildings": buildings,
        "building_groups": building_groups,
        "pms": pms,
        "companies": companies,
        "regions": regions,
        "country_types": country_types,
    }


def load_tag_state_types(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    return {
        (str(tag), str(state)): str(state_type or "incorporated")
        for tag, state, state_type in conn.execute(
            "SELECT tag, state, state_type FROM st"
        )
    }


def load_hub_provinces(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """province key -> hub info from ref_sr hub columns only."""
    grouped: dict[int, list[tuple[str, str]]] = {}
    hub_types = ("city", "port", "farm", "mine", "wood")
    for state, city, port, farm, mine, wood in conn.execute(
        "SELECT state, city, port, farm, mine, wood FROM ref_sr"
    ):
        state = str(state)
        values = {
            "city": str(city or "").strip(),
            "port": str(port or "").strip(),
            "farm": str(farm or "").strip(),
            "mine": str(mine or "").strip(),
            "wood": str(wood or "").strip(),
        }
        for hub in hub_types:
            province = values[hub]
            if not province:
                continue
            key = province_hex_to_key(province)
            grouped.setdefault(key, []).append((hub, state))

    mapping: dict[int, dict[str, str]] = {}
    priority = {hub: i for i, hub in enumerate(hub_types)}
    for key, entries in grouped.items():
        entries.sort(key=lambda item: priority[item[0]])
        primary_hub, state = entries[0]
        info = {"state": state, "hub_type": primary_hub}
        if len(entries) > 1:
            info["also"] = [{"hub_type": hub} for hub, _ in entries[1:]]
        mapping[key] = info
    return mapping


def load_meta_json(conn: sqlite3.Connection, *, db_name: str) -> dict[str, str]:
    """Export metadata stored in the database itself."""
    rows = {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM meta")}
    return {
        "database": db_name,
        "built_at": rows.get("built_at", ""),
    }


def write_provinces_png(conn: sqlite3.Connection, output_path: Path) -> bytes:
    png_bytes = load_provinces_png_bytes(conn)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png_bytes)
    return png_bytes
