"""Tests for cultural homeland map layer."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.state_geo import change_homeland  # noqa: E402
from interactive_map.homeland_layer import (  # noqa: E402
    HOMELAND_LABEL_MULTI,
    HOMELAND_LABEL_NONE,
    build_homeland_labels,
    build_homeland_palette,
    load_state_homelands,
    render_homeland_png,
)
from interactive_map.map_session import MapSession  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


class HomelandLayerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "map_db"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def setUp(self) -> None:
        self.session = MapSession.open(DB)

    def tearDown(self) -> None:
        self.session.close()

    def test_load_state_homelands_from_db(self) -> None:
        homelands = load_state_homelands(self.session.conn)
        self.assertGreater(len(homelands), 100)
        single = next(
            state for state, cultures in homelands.items() if len(cultures) == 1
        )
        self.assertGreater(len(homelands[single]), 0)

    def test_build_homeland_labels_single_multi_none(self) -> None:
        state_homelands = load_state_homelands(self.session.conn)
        labels = build_homeland_labels(
            self.session.model,
            self.session.static.province_geographic_state,
            state_homelands,
        )
        palette = build_homeland_palette(self.session.conn)

        single_state = next(
            state for state, cultures in state_homelands.items() if len(cultures) == 1
        )
        multi_state = next(
            (state for state, cultures in state_homelands.items() if len(cultures) > 1),
            None,
        )
        single_key = next(
            key
            for key, geo in self.session.static.province_geographic_state.items()
            if geo == single_state
        )
        self.assertEqual(labels[single_key], state_homelands[single_state][0])
        self.assertIn(labels[single_key], palette)

        if multi_state:
            multi_key = next(
                key
                for key, geo in self.session.static.province_geographic_state.items()
                if geo == multi_state
            )
            self.assertEqual(labels[multi_key], HOMELAND_LABEL_MULTI)

        none_state = next(
            state
            for state in {
                row[0]
                for row in self.session.conn.execute("SELECT state FROM geo_state")
            }
            if state not in state_homelands
        )
        none_key = next(
            key
            for key, geo in self.session.static.province_geographic_state.items()
            if geo == none_state
        )
        self.assertEqual(labels[none_key], HOMELAND_LABEL_NONE)

    def test_render_homeland_png(self) -> None:
        png = render_homeland_png(
            self.session.model,
            self.session.conn,
            province_geographic_state=self.session.static.province_geographic_state,
        )
        self.assertGreater(len(png), 1000)

    def test_apply_homeland_edit_invalidates_layer(self) -> None:
        before = self.session.layer_png("homeland")
        rev_before = self.session.revision
        conn = self.session.conn
        row = conn.execute(
            """
            SELECT state, culture FROM geo_homeland
            WHERE state IN (
                SELECT state FROM geo_homeland
                GROUP BY state HAVING COUNT(*) = 1
            )
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            self.skipTest("no single-homeland state")
        state, culture = str(row[0]), str(row[1])

        conn.execute("BEGIN")
        try:
            result = change_homeland(
                conn,
                state=state,
                culture="french",
                action="add",
            )
            rev = self.session.apply_homeland_edit(state)
            after = self.session.layer_png("homeland")
            self.assertGreater(rev, rev_before)
            self.assertIsNot(before, after)
            self.assertIn("french", result["homelands"])
        finally:
            conn.rollback()


if __name__ == "__main__":
    unittest.main()
