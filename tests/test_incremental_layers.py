"""Tests for incremental territory layer updates."""

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.edit.transfer import set_owner  # noqa: E402
from interactive_map.incremental_layers import (  # noqa: E402
    build_country_border_segments,
    build_province_neighbors,
    build_province_pixel_indices,
    collect_dirty_province_keys,
    compute_dirty_bbox,
    patch_country_border_rgba,
)
from interactive_map.borders import render_border_country_rgba  # noqa: E402
from interactive_map.map_session import MapSession  # noqa: E402
from interactive_map.png_util import province_db_to_hex, province_hex_to_key  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


class IncrementalLayersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "src"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

    def setUp(self) -> None:
        self.session = MapSession.open(DB)

    def tearDown(self) -> None:
        self.session.close()

    def _pick_transferable_province(self) -> tuple[str, str, str]:
        row = self.session.conn.execute(
            """
            SELECT sp.province, sp.tag, sp.state
            FROM st_prov sp
            JOIN ref_tag rt ON rt.tag != sp.tag
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            self.skipTest("no transferable province")
        province, from_tag, state = row
        other = self.session.conn.execute(
            "SELECT tag FROM ref_tag WHERE tag != ? LIMIT 1",
            (from_tag,),
        ).fetchone()
        if other is None:
            self.skipTest("no alternate tag")
        return str(province), str(from_tag), str(other[0])

    def test_apply_territory_edit_leaves_unrelated_pixels_unchanged(self) -> None:
        province, from_tag, to_tag = self._pick_transferable_province()
        indices = build_province_pixel_indices(self.session.rgb_keys)

        _ = self.session.layer_png("ownership")
        before_arr = np.array(
            Image.open(io.BytesIO(self.session.layer_png("ownership")))
        )
        rev_before = self.session.revision

        conn = self.session.conn
        conn.execute("BEGIN")
        try:
            result = set_owner(
                conn,
                province_hex=province_db_to_hex(province),
                new_tag=to_tag,
                origin_tag=from_tag,
            )
            dirty = collect_dirty_province_keys(conn, result)
            prov_key = province_hex_to_key(province)
            self.assertIn(prov_key, dirty)

            rev = self.session.apply_territory_edit(result, view_layer="ownership")
            after_arr = np.array(
                Image.open(io.BytesIO(self.session.layer_png("ownership")))
            )

            dirty_pixels: set[int] = set()
            for key in dirty:
                dirty_pixels.update(indices[key].tolist())

            flat_before = before_arr.reshape(-1, 3)
            flat_after = after_arr.reshape(-1, 3)
            unchanged = np.array(
                [idx for idx in range(flat_before.shape[0]) if idx not in dirty_pixels],
                dtype=np.int64,
            )
            np.testing.assert_array_equal(
                flat_before[unchanged],
                flat_after[unchanged],
            )
            self.assertGreater(rev, rev_before)
            self.assertEqual(self.session.model.ownership_tag.get(prov_key), to_tag)
        finally:
            conn.rollback()

    def test_incremental_does_not_full_refresh_model_reference(self) -> None:
        province, from_tag, to_tag = self._pick_transferable_province()
        terrain_ref = self.session.model.terrain
        _ = self.session.layer_png("ownership")

        conn = self.session.conn
        conn.execute("BEGIN")
        try:
            result = set_owner(
                conn,
                province_hex=province_db_to_hex(province),
                new_tag=to_tag,
                origin_tag=from_tag,
            )
            self.session.apply_territory_edit(result, view_layer="ownership")
            self.assertIs(self.session.model.terrain, terrain_ref)
        finally:
            conn.rollback()

    def test_border_country_patch_runs_after_transfer(self) -> None:
        province, from_tag, to_tag = self._pick_transferable_province()
        _ = self.session.layer_png("border_country")
        before_rev = self.session.revision

        conn = self.session.conn
        conn.execute("BEGIN")
        try:
            result = set_owner(
                conn,
                province_hex=province_db_to_hex(province),
                new_tag=to_tag,
                origin_tag=from_tag,
            )
            rev = self.session.apply_territory_edit(result, view_layer="ownership")
            border_png = self.session.layer_png("border_country")
            self.assertGreater(rev, before_rev)
            self.assertGreater(len(border_png), 1000)
            self.assertIn("border_country", self.session._layer_rgb)
        finally:
            conn.rollback()

    def test_apply_territory_edit_emits_small_layer_patches(self) -> None:
        province, from_tag, to_tag = self._pick_transferable_province()
        full_png = self.session.layer_png("ownership")
        _ = self.session.layer_png("incorporation")

        conn = self.session.conn
        conn.execute("BEGIN")
        try:
            result = set_owner(
                conn,
                province_hex=province_db_to_hex(province),
                new_tag=to_tag,
                origin_tag=from_tag,
            )
            self.session.apply_territory_edit(result, view_layer="ownership")
            patches = self.session.take_territory_patches_for_view()
            self.assertIn("ownership", patches)
            self.assertIn("border_country", patches)
            patch_bytes = len(patches["ownership"]["png_b64"])
            self.assertLess(patch_bytes, len(full_png) // 10)
            bbox_area = patches["ownership"]["w"] * patches["ownership"]["h"]
            self.assertLess(bbox_area, self.session.width * self.session.height // 10)
        finally:
            conn.rollback()

    def test_compute_dirty_bbox_from_province_key(self) -> None:
        indices = build_province_pixel_indices(self.session.rgb_keys)
        key = next(iter(indices))
        bbox = compute_dirty_bbox(
            {key},
            indices,
            [],
            {key},
            width=self.session.width,
            height=self.session.height,
        )
        self.assertIsNotNone(bbox)
        x, y, w, h = bbox
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)
        self.assertLess(x + w, self.session.width + 1)
        self.assertLess(y + h, self.session.height + 1)

    def test_patch_country_border_clears_both_pixels_when_tags_merge(self) -> None:
        rgb_keys = np.array([[1, 1, 2], [1, 1, 2]], dtype=np.int32)
        segments = build_country_border_segments(rgb_keys)
        province_tag_state = {1: ("USA", "S1"), 2: ("MEX", "S2")}
        rgba = render_border_country_rgba(rgb_keys, province_tag_state)
        self.assertGreater(int(rgba[0, 1, 3]), 0)
        self.assertGreater(int(rgba[0, 2, 3]), 0)

        province_tag_state[2] = ("USA", "S2")
        patch_country_border_rgba(
            rgba,
            segments,
            province_tag_state,
            dirty_keys={1, 2},
        )
        self.assertEqual(int(rgba[0, 1, 3]), 0)
        self.assertEqual(int(rgba[0, 2, 3]), 0)

    def test_patch_country_border_keeps_land_sea_edge(self) -> None:
        rgb_keys = np.array([[1, 0], [1, 0]], dtype=np.int32)
        segments = build_country_border_segments(rgb_keys)
        province_tag_state = {1: ("USA", "S1")}
        rgba = render_border_country_rgba(rgb_keys, province_tag_state)
        self.assertGreater(int(rgba[0, 0, 3]), 0)
        self.assertGreater(int(rgba[0, 1, 3]), 0)

        patch_country_border_rgba(
            rgba,
            segments,
            province_tag_state,
            dirty_keys={1},
        )
        self.assertGreater(int(rgba[0, 0, 3]), 0)
        self.assertGreater(int(rgba[0, 1, 3]), 0)


if __name__ == "__main__":
    unittest.main()
