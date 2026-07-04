from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from constants import RESOURCE_COLUMNS  # noqa: E402
from load_origin_sqlite import build_origin_database  # noqa: E402


class OriginSqliteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from building_flat import assign_ids, parse_history_buildings_dir
        from country_definitions_flat import parse_country_definitions_paths
        from named_colors_flat import build_named_color_lookup, parse_named_colors_paths
        from history_countries_tech_flat import (
            filter_by_ownership,
            parse_countries_paths,
        )
        from history_pops_flat import parse_pops_dir
        from history_states_flat import merge_population_into_ownership, parse_states_dir
        from market_subordination import parse_market_subordination_dirs
        from state_region_flat import parse_state_regions_dir

        vanilla = Path(
            "/home/liulingda/snap/steam/common/.local/share/Steam/steamapps/common/Victoria 3/game"
        )
        if not vanilla.is_dir():
            from config import load_config

            config = load_config()
            if config.vanilla.is_dir():
                vanilla = config.vanilla
            else:
                raise unittest.SkipTest("未找到原版游戏目录")

        region_rows = parse_state_regions_dir(
            paths=list((vanilla / "map_data/state_regions").glob("*.txt")),
            resource_columns=RESOURCE_COLUMNS,
        )
        pops = parse_pops_dir(
            paths=list((vanilla / "common/history/pops").glob("*.txt"))
        )
        meta_rows, own_rows = parse_states_dir(
            paths=list((vanilla / "common/history/states").glob("*.txt"))
        )
        own_rows = merge_population_into_ownership(own_rows, pops)
        market_rows, _ = parse_market_subordination_dirs(
            diplomacy_paths=list(
                (vanilla / "common/history/diplomacy").glob("*.txt")
            ),
            power_blocs_paths=list(
                (vanilla / "common/history/power_blocs").glob("*.txt")
            ),
        )
        building_rows = assign_ids(
            parse_history_buildings_dir(
                paths=list((vanilla / "common/history/buildings").glob("*.txt"))
            )
        )
        tech_rows = filter_by_ownership(
            parse_countries_paths(
                paths=list((vanilla / "common/history/countries").glob("*.txt"))
            ),
            own_rows,
        )
        named_color_rows = parse_named_colors_paths(
            paths=list((vanilla / "common/named_colors").glob("*.txt"))
        )
        named_color_lookup = build_named_color_lookup(named_color_rows)
        country_definition_rows = parse_country_definitions_paths(
            paths=list((vanilla / "common/country_definitions").glob("*.txt")),
            named_colors=named_color_lookup,
        )
        cls._tmp_db = Path(__file__).resolve().parent / "_test_origin.sqlite"
        cls.conn = build_origin_database(
            cls._tmp_db,
            region_rows=region_rows,
            meta_rows=meta_rows,
            own_rows=own_rows,
            market_rows=market_rows,
            country_tech_rows=tech_rows,
            country_definition_rows=country_definition_rows,
            named_color_rows=named_color_rows,
            building_rows=building_rows,
            resource_columns=RESOURCE_COLUMNS,
        )
        cls.conn.row_factory = sqlite3.Row

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "conn"):
            cls.conn.close()
        if cls._tmp_db.is_file():
            cls._tmp_db.unlink()

    def test_table_counts(self) -> None:
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM state_region").fetchone()[0],
            self.conn.execute("SELECT COUNT(*) FROM state").fetchone()[0],
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM tag").fetchone()[0],
            self.conn.execute(
                "SELECT COUNT(DISTINCT tag) FROM tag__state"
            ).fetchone()[0],
        )

    def test_state_meta_subset_of_state(self) -> None:
        orphan = self.conn.execute(
            """
            SELECT COUNT(*) FROM state_meta m
            WHERE NOT EXISTS (SELECT 1 FROM state s WHERE s.state = m.state)
            """
        ).fetchone()[0]
        self.assertEqual(orphan, 0)

    def test_tag__state_foreign_keys(self) -> None:
        orphan = self.conn.execute(
            """
            SELECT COUNT(*) FROM tag__state ts
            WHERE NOT EXISTS (SELECT 1 FROM tag t WHERE t.tag = ts.tag)
               OR NOT EXISTS (SELECT 1 FROM state s WHERE s.state = ts.state)
            """
        ).fetchone()[0]
        self.assertEqual(orphan, 0)

    def test_building_foreign_keys(self) -> None:
        orphan = self.conn.execute(
            """
            SELECT COUNT(*) FROM tag__state__building b
            WHERE NOT EXISTS (
                SELECT 1 FROM tag__state ts
                WHERE ts.tag = b.tag AND ts.state = b.state
            )
            """
        ).fetchone()[0]
        self.assertEqual(orphan, 0)

    def test_market_master_tags_active(self) -> None:
        orphan = self.conn.execute(
            """
            SELECT COUNT(*) FROM tag__market_master m
            WHERE NOT EXISTS (SELECT 1 FROM tag t WHERE t.tag = m.tag)
               OR NOT EXISTS (SELECT 1 FROM tag t WHERE t.tag = m.market_master)
            """
        ).fetchone()[0]
        self.assertEqual(orphan, 0)

    def test_technology_covers_active_tags(self) -> None:
        missing = self.conn.execute(
            """
            SELECT COUNT(*) FROM tag t
            WHERE NOT EXISTS (SELECT 1 FROM tag__technology tt WHERE tt.tag = t.tag)
            """
        ).fetchone()[0]
        self.assertEqual(missing, 0)

    def test_active_tags_have_country_definitions(self) -> None:
        missing = self.conn.execute(
            """
            SELECT COUNT(*) FROM tag t
            WHERE NOT EXISTS (
                SELECT 1 FROM country_definition cd WHERE cd.tag = t.tag
            )
            """
        ).fetchone()[0]
        self.assertEqual(missing, 0)

    def test_country_definition_rgb_range(self) -> None:
        invalid = self.conn.execute(
            """
            SELECT COUNT(*) FROM country_definition
            WHERE r NOT BETWEEN 0 AND 255
               OR g NOT BETWEEN 0 AND 255
               OR b NOT BETWEEN 0 AND 255
            """
        ).fetchone()[0]
        self.assertEqual(invalid, 0)

    def test_foreign_key_enforcement(self) -> None:
        conn = sqlite3.connect(self._tmp_db)
        conn.execute("PRAGMA foreign_keys = ON")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO state (state) VALUES ('STATE_FAKE')")
            conn.commit()
        conn.close()


if __name__ == "__main__":
    unittest.main()
