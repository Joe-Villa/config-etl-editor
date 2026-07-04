"""Runtime map session: parse provinces.png once, reload labels from SQL on refresh."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

import numpy as np

from interactive_map.annotate import build_terrain_json, render_terrain_png
from interactive_map.borders import render_border_country_png, render_border_pngs
from interactive_map.compositor import ProvinceKeyIndex, count_labeled_pixels, province_key_index
from interactive_map.db_reader import (
    load_countries_json,
    load_layer_png_bytes,
    load_meta_json,
    load_names_json,
    load_names_json_all_locales,
    load_names_json_merged_all_locales,
    load_provinces_json,
    load_provinces_png_bytes,
    load_states_json,
    load_tag_country_types,
    load_tag_state_types,
)
from interactive_map.strategic_regions import load_strategic_regions_json
from interactive_map.hubs import build_hubs_json, render_hubs_png
from interactive_map.pop_layers import (
    build_pop_culture_json,
    build_pop_religion_json,
    build_pop_total_json,
    build_slavery_json,
    render_pop_culture_png,
    render_pop_religion_png,
    render_pop_total_png,
    render_slavery_png,
)
from interactive_map.country_type_layer import (
    build_country_type_json,
    build_country_type_labels,
    render_country_type_png,
)
from interactive_map.building_levels import (
    build_building_level_json,
    render_building_level_png,
)
from interactive_map.foreign_investment import (
    build_foreign_investment_json,
    render_foreign_investment_png,
)
from interactive_map.incorporation import (
    build_incorporation_json,
    incorporation_counts,
    render_incorporation_png,
)
from interactive_map.claim_layer import build_claims_json, render_claims_png
from interactive_map.homeland_layer import build_homeland_json, render_homeland_png
from interactive_map.palette import COUNTRY_TYPE_PALETTE, INCORPORATION_PALETTE
from interactive_map.incremental_layers import (
    DYNAMIC_VIEW_LAYERS,
    TERRITORY_MAIN_VIEW_LAYERS,
    TERRITORY_PATCH_LAYERS,
    build_country_border_segments,
    build_province_neighbors,
    build_province_pixel_indices,
    build_territory_layer_array,
    build_territory_layer_arrays,
    collect_dirty_province_keys,
    compute_dirty_bbox,
    edit_touches_foreign_investment,
    encode_territory_layer_pngs,
    encode_territory_layer_patches,
    expand_with_neighbors,
    paint_provinces_rgb,
    patch_country_border_rgba,
    patch_incorporation_for_scopes,
    patch_scenario_for_provinces,
    territory_patches_for_view,
)
from interactive_map.compositor import encode_png_rgb
from interactive_map.borders import encode_rgba_png
from interactive_map.png_util import png_size, province_rgb_keys_from_bytes
from interactive_map.precompute_layers import STATIC_LAYER_NAMES, STATIC_META_KEYS
from interactive_map.province_model import (
    ProvinceModel,
    ScenarioOverlay,
    StaticMapBase,
    load_scenario_overlay,
    load_static_map_base,
    merge_province_model,
)
from interactive_map.render import build_ownership_palette, render_ownership_png
from interactive_map.strategic_regions import render_strategic_region_png

LAYER_NAMES = (
    "ownership",
    "country_type",
    "terrain",
    "incorporation",
    "homeland",
    "claims",
    "foreign_investment",
    "building_level",
    "slavery",
    "pop_total",
    "pop_culture",
    "pop_religion",
    "hubs",
    "strategic_region",
    "raw",
    "border_province",
    "border_state",
    "border_country",
)

STATIC_LAYERS = frozenset(STATIC_LAYER_NAMES)
DYNAMIC_LAYERS = frozenset(LAYER_NAMES) - STATIC_LAYERS

IMMUTABLE_JSON_DOCUMENTS = frozenset(
    {"names", "countries", "terrain", "hubs", "strategic_regions"}
)
MUTABLE_JSON_DOCUMENTS = frozenset(
    {
        "provinces",
        "states",
        "incorporation",
        "country_type",
        "homeland",
        "claims",
        "foreign_investment",
        "building_level",
        "slavery",
        "pop_total",
        "pop_culture",
        "pop_religion",
        "meta",
    }
)

JSON_DOCUMENTS = tuple(IMMUTABLE_JSON_DOCUMENTS | MUTABLE_JSON_DOCUMENTS)

T = TypeVar("T")

# Scenario JSON/meta before the province raster is parsed at first map draw.
_PLACEHOLDER_RGB_KEYS = np.empty(0, dtype=np.uint32)


def _load_names(conn: sqlite3.Connection) -> dict[str, dict[str, dict[str, str]]]:
    try:
        from editor_config import load_config

        return load_names_json_merged_all_locales(conn, load_config().vanilla)
    except (ImportError, FileNotFoundError, OSError, ValueError):
        return load_names_json_all_locales(conn)


@dataclass
class MapSession:
    """Hold one sqlite connection; parse provinces.png once on first territory draw."""

    db_path: Path
    conn: sqlite3.Connection
    png_bytes: bytes
    width: int
    height: int
    static: StaticMapBase
    static_meta: dict[str, int]
    model: ProvinceModel
    province_tag_state: dict[int, tuple[str, str]]
    revision: int = 0
    _rgb_keys: np.ndarray | None = field(default=None, repr=False)
    _key_index: ProvinceKeyIndex | None = field(default=None, repr=False)
    _layer_cache: dict[str, bytes] = field(default_factory=dict)
    _layer_rgb: dict[str, Any] = field(default_factory=dict)
    _json_cache: dict[str, Any] = field(default_factory=dict)
    _province_indices: dict[int, Any] | None = None
    _province_neighbors: dict[int, set[int]] | None = None
    _border_segments: list[tuple[int, int, int, int]] | None = None
    _ownership_palette: dict[str, tuple[int, int, int]] | None = None
    _tag_country_types: dict[str, str] | None = None
    _tag_state_types: dict[tuple[str, str], str] | None = None
    _last_territory_patches: dict[str, dict[str, Any]] | None = field(
        default=None, repr=False
    )
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @contextmanager
    def using_conn(self) -> Iterator[sqlite3.Connection]:
        """Serialize sqlite access across HTTP worker threads."""
        with self._lock:
            yield self.conn

    def read(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        with self._lock:
            return fn(self.conn)

    @property
    def raster_parsed(self) -> bool:
        return self._rgb_keys is not None

    @property
    def rgb_keys(self) -> np.ndarray:
        """Parsed province raster; available after first territory-layer draw."""
        self._ensure_province_raster()
        assert self._rgb_keys is not None
        return self._rgb_keys

    def geographic_model_for_json(self) -> ProvinceModel:
        """Geographic labels for bootstrap JSON without parsing provinces.png pixels."""
        return merge_province_model(
            _PLACEHOLDER_RGB_KEYS, self.static, ScenarioOverlay()
        )

    def _ensure_province_raster(self) -> None:
        """Decode provinces.png once per session; reuse for all dynamic layers."""
        if self._rgb_keys is not None:
            return
        self._rgb_keys, (w, h) = province_rgb_keys_from_bytes(self.png_bytes)
        if (w, h) != (self.width, self.height):
            self.width, self.height = w, h
        self._key_index = province_key_index(self._rgb_keys)
        scenario = load_scenario_overlay(self.conn)
        self.model = merge_province_model(
            self._rgb_keys,
            self.static,
            scenario,
            key_index=self._key_index,
        )
        self.province_tag_state = scenario.province_tag_state

    def _merge_scenario_model(self, scenario: ScenarioOverlay) -> None:
        self.province_tag_state = scenario.province_tag_state
        rgb_keys = self._rgb_keys if self._rgb_keys is not None else _PLACEHOLDER_RGB_KEYS
        self.model = merge_province_model(
            rgb_keys,
            self.static,
            scenario,
            key_index=self._key_index,
        )

    @classmethod
    def open(cls, db_path: Path) -> MapSession:
        db_path = db_path.resolve()
        conn = sqlite3.connect(db_path, check_same_thread=False)
        from interactive_map.edit.atomic import configure_edit_connection

        configure_edit_connection(conn)
        png_bytes = load_provinces_png_bytes(conn)
        width, height = png_size(png_bytes)
        static = load_static_map_base(conn)
        static_meta = cls._load_static_meta(conn, width, height, static)
        scenario = load_scenario_overlay(conn)
        session = cls(
            db_path=db_path,
            conn=conn,
            png_bytes=png_bytes,
            width=width,
            height=height,
            static=static,
            static_meta=static_meta,
            model=merge_province_model(_PLACEHOLDER_RGB_KEYS, static, scenario),
            province_tag_state=scenario.province_tag_state,
        )
        session._prime_immutable_json_cache()
        return session

    @classmethod
    def _load_static_meta(
        cls,
        conn: sqlite3.Connection,
        width: int,
        height: int,
        static: StaticMapBase,
    ) -> dict[str, int]:
        rows = {
            str(key): str(value)
            for key, value in conn.execute(
                "SELECT key, value FROM meta WHERE key IN ({})".format(
                    ",".join("?" for _ in STATIC_META_KEYS)
                ),
                STATIC_META_KEYS,
            )
        }
        if len(rows) == len(STATIC_META_KEYS):
            meta = {key: int(rows[key]) for key in STATIC_META_KEYS}
            # map_* always follow provinces.png (older builds stored h/w swapped in meta)
            meta["map_width"] = width
            meta["map_height"] = height
            meta["total_pixels"] = width * height
            return meta

        from interactive_map.annotate import terrain_counts as tc

        model = merge_province_model(
            _PLACEHOLDER_RGB_KEYS, static, ScenarioOverlay()
        )
        prime, normal, impassable = tc(model)
        names = _load_names(conn)
        zh_names = names["zh"]
        return {
            "map_width": width,
            "map_height": height,
            "total_pixels": width * height,
            "prime_land_count": prime,
            "normal_land_count": normal,
            "impassable_count": impassable,
            "hub_provinces": len(static.hub_info),
            "tag_name_count": len(zh_names["tags"]),
            "state_name_count": len(zh_names["states"]),
            "hub_name_count": len(zh_names["hubs"]),
            "culture_name_count": len(zh_names["cultures"]),
            "religion_name_count": len(zh_names["religions"]),
            "building_name_count": len(zh_names["buildings"]),
            "building_group_name_count": len(zh_names["building_groups"]),
            "pm_name_count": len(zh_names["pms"]),
            "company_name_count": len(zh_names["companies"]),
        }

    def _prime_immutable_json_cache(self) -> None:
        geographic_model = self.geographic_model_for_json()
        self._json_cache = {
            "names": _load_names(self.conn),
            "countries": load_countries_json(self.conn),
            "terrain": build_terrain_json(geographic_model),
            "hubs": build_hubs_json(geographic_model),
            "strategic_regions": load_strategic_regions_json(self.conn),
        }

    def refresh(self) -> int:
        """Reload editable scenario tables only; keep ref_* / static assets cached."""
        with self._lock:
            scenario = load_scenario_overlay(self.conn)
            self._merge_scenario_model(scenario)
            self._tag_state_types = load_tag_state_types(self.conn)
            for name in DYNAMIC_LAYERS:
                self._layer_cache.pop(name, None)
            self._layer_rgb.clear()
            self.revision += 1
            return self.revision

    def apply_territory_edit(
        self,
        result: dict[str, Any],
        *,
        view_layer: str | None = None,
    ) -> int:
        """Patch ownership/incorporation/country-border layers for affected provinces only."""
        with self._lock:
            self._ensure_province_raster()
            self._ensure_incremental_structures()
            self._tag_state_types = load_tag_state_types(self.conn)

            dirty_paint = collect_dirty_province_keys(self.conn, result)
            if not dirty_paint:
                scenario = load_scenario_overlay(self.conn)
                self._merge_scenario_model(scenario)
                for layer_name in (
                    "ownership",
                    "incorporation",
                    "country_type",
                    "border_country",
                    "building_level",
                    "slavery",
                    "pop_total",
                    "pop_culture",
                    "pop_religion",
                ):
                    self._layer_cache.pop(layer_name, None)
                    self._layer_rgb.pop(layer_name, None)
                self.revision += 1
                return self.revision

            op = str(result.get("op", ""))
            if op == "incorporate_all_states":
                tag = str(result.get("tag") or "")
                dirty_paint = patch_incorporation_for_scopes(
                    self.conn,
                    self.model,
                    tag,
                    [str(state) for state in result.get("states_updated", [])],
                    tag_state_types=self._tag_state_types,
                )
            elif op == "change_state_type":
                tag = str(result.get("tag") or "")
                state = str(result.get("state") or "")
                dirty_paint = patch_incorporation_for_scopes(
                    self.conn,
                    self.model,
                    tag,
                    [state],
                    tag_state_types=self._tag_state_types,
                )
            else:
                patch_scenario_for_provinces(
                    self.conn,
                    self.model,
                    self.province_tag_state,
                    dirty_paint,
                    tag_state_types=self._tag_state_types,
                )

            dirty_border = expand_with_neighbors(self._province_neighbors, dirty_paint)

            if view_layer in TERRITORY_MAIN_VIEW_LAYERS:
                active_main = view_layer
            elif view_layer is None:
                active_main = "ownership"
            else:
                active_main = None
            patch_layers: list[str] = []
            if active_main is not None:
                self._ensure_territory_layer_rgb(active_main)
                if active_main == "ownership":
                    paint_provinces_rgb(
                        self._layer_rgb["ownership"],
                        self._province_indices,
                        dirty_paint,
                        self.model.ownership_tag,
                        self._ownership_palette,
                    )
                elif active_main == "incorporation":
                    paint_provinces_rgb(
                        self._layer_rgb["incorporation"],
                        self._province_indices,
                        dirty_paint,
                        self.model.incorporation,
                        INCORPORATION_PALETTE,
                    )
                elif active_main == "country_type":
                    paint_provinces_rgb(
                        self._layer_rgb["country_type"],
                        self._province_indices,
                        dirty_paint,
                        build_country_type_labels(
                            self.model, self._tag_country_types
                        ),
                        COUNTRY_TYPE_PALETTE,
                    )
                patch_layers.append(active_main)

            self._ensure_territory_layer_rgb("border_country")
            patch_country_border_rgba(
                self._layer_rgb["border_country"],
                self._border_segments,
                self.province_tag_state,
                dirty_border,
            )
            patch_layers.append("border_country")

            bbox = compute_dirty_bbox(
                dirty_paint,
                self._province_indices,
                self._border_segments,
                dirty_border,
                width=self.width,
                height=self.height,
            )
            if bbox is not None:
                self._last_territory_patches = encode_territory_layer_patches(
                    self._layer_rgb,
                    bbox,
                    layers=tuple(patch_layers),
                )
            else:
                self._last_territory_patches = None

            for layer_name in patch_layers:
                self._layer_cache.pop(layer_name, None)

            if edit_touches_foreign_investment(result):
                self._layer_cache.pop("foreign_investment", None)

            self._layer_cache.pop("building_level", None)
            for pop_layer in ("slavery", "pop_total", "pop_culture", "pop_religion"):
                self._layer_cache.pop(pop_layer, None)

            self.revision += 1
            return self.revision

    def _ensure_territory_layer_rgb(self, name: str) -> None:
        if name in self._layer_rgb:
            return
        self._ensure_province_raster()
        self._ensure_incremental_structures()
        self._layer_rgb[name] = build_territory_layer_array(
            name,
            self.model,
            self.province_tag_state,
            self._ownership_palette,
            self._tag_country_types,
        )

    def take_territory_patches_for_view(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if not self._last_territory_patches:
                return {}
            payload = territory_patches_for_view(self._last_territory_patches)
            self._last_territory_patches = None
            return payload

    def _encode_territory_layer_from_rgb(self, name: str) -> bytes:
        array = self._layer_rgb[name]
        if name == "border_country":
            return encode_rgba_png(array)
        return encode_png_rgb(array)

    def apply_homeland_edit(self, geo_state: str = "") -> int:
        """Invalidate homeland layer after ``geo_homeland`` changes."""
        del geo_state  # reserved for future per-state patch
        with self._lock:
            self._layer_cache.pop("homeland", None)
            self._layer_rgb.pop("homeland", None)
            self.revision += 1
            return self.revision

    def apply_claim_edit(self, geo_state: str = "") -> int:
        """Invalidate claims layer after ``geo_claim`` changes."""
        del geo_state
        with self._lock:
            self._layer_cache.pop("claims", None)
            self._layer_rgb.pop("claims", None)
            self.revision += 1
            return self.revision

    def bump_revision(self) -> int:
        with self._lock:
            self.revision += 1
            return self.revision

    def invalidate_layer_caches(self, *names: str) -> int:
        """Drop cached PNG/RGB for named layers and bump revision."""
        with self._lock:
            for name in names:
                self._layer_cache.pop(name, None)
                self._layer_rgb.pop(name, None)
            self.revision += 1
            return self.revision

    def refresh_view_layer(self, layer: str) -> int:
        """Force full rebuild of one dynamic view layer from current sqlite state."""
        if layer not in DYNAMIC_VIEW_LAYERS:
            raise ValueError(f"图层 {layer} 为静态视图，无法刷新")
        with self._lock:
            self._ensure_province_raster()
            scenario = load_scenario_overlay(self.conn)
            self._merge_scenario_model(scenario)
            self._tag_state_types = load_tag_state_types(self.conn)
            self._layer_cache.pop(layer, None)
            self._layer_rgb.pop(layer, None)
            self._ensure_incremental_structures()
            if layer == "ownership":
                self._ownership_palette = build_ownership_palette(self.conn)
            elif layer == "country_type":
                self._tag_country_types = load_tag_country_types(self.conn)
            if layer in TERRITORY_MAIN_VIEW_LAYERS:
                self._layer_rgb[layer] = build_territory_layer_array(
                    layer,
                    self.model,
                    self.province_tag_state,
                    self._ownership_palette,
                    self._tag_country_types,
                )
            png_bytes = self._render_layer(layer)
            self._layer_cache[layer] = png_bytes
            self.revision += 1
            return self.revision

    def _ensure_incremental_structures(self) -> None:
        assert self._rgb_keys is not None
        if self._province_indices is None:
            self._province_indices = build_province_pixel_indices(self._rgb_keys)
        if self._province_neighbors is None:
            self._province_neighbors = build_province_neighbors(self._rgb_keys)
        if self._border_segments is None:
            self._border_segments = build_country_border_segments(self._rgb_keys)
        if self._ownership_palette is None:
            self._ownership_palette = build_ownership_palette(self.conn)
        if self._tag_country_types is None:
            self._tag_country_types = load_tag_country_types(self.conn)
        if self._tag_state_types is None:
            self._tag_state_types = load_tag_state_types(self.conn)

    def _rebuild_territory_layers(self) -> None:
        self._ensure_incremental_structures()
        self._layer_rgb = build_territory_layer_arrays(
            self.model,
            self.province_tag_state,
            self._ownership_palette,
            self._tag_country_types,
        )
        for layer_name, png_bytes in encode_territory_layer_pngs(self._layer_rgb).items():
            self._layer_cache[layer_name] = png_bytes

    def close(self) -> None:
        self.conn.close()

    def json_document(self, name: str) -> Any:
        if name not in JSON_DOCUMENTS:
            raise KeyError(name)
        with self._lock:
            if name in IMMUTABLE_JSON_DOCUMENTS:
                return self._json_cache[name]
            if name == "provinces":
                return load_provinces_json(self.conn)
            if name == "states":
                return load_states_json(self.conn)
            if name == "incorporation":
                return build_incorporation_json(self.conn)
            if name == "country_type":
                return build_country_type_json(self.conn)
            if name == "homeland":
                return build_homeland_json(self.conn)
            if name == "claims":
                return build_claims_json(self.conn)
            if name == "foreign_investment":
                return build_foreign_investment_json(
                    self.conn,
                    province_tag_state=self.province_tag_state,
                )
            if name == "building_level":
                return build_building_level_json(
                    self.conn,
                    province_tag_state=self.province_tag_state,
                )
            if name == "slavery":
                return build_slavery_json(
                    self.conn,
                    province_tag_state=self.province_tag_state,
                )
            if name == "pop_total":
                return build_pop_total_json(
                    self.conn,
                    province_tag_state=self.province_tag_state,
                )
            if name == "pop_culture":
                return build_pop_culture_json(
                    self.conn,
                    province_tag_state=self.province_tag_state,
                )
            if name == "pop_religion":
                return build_pop_religion_json(
                    self.conn,
                    province_tag_state=self.province_tag_state,
                )
            return self.meta_json()

    def meta_json(self) -> dict[str, Any]:
        provinces_json = load_provinces_json(self.conn)
        states_json = load_states_json(self.conn)
        inc_prov, uninc_prov = incorporation_counts(self.model)
        if self._rgb_keys is None:
            own_painted = 0
        else:
            own_painted = count_labeled_pixels(self._rgb_keys, self.model.ownership_tag)
        return {
            **load_meta_json(self.conn, db_name=self.db_path.name),
            **self.static_meta,
            "revision": self.revision,
            "width": self.static_meta["map_width"],
            "height": self.static_meta["map_height"],
            "province_count": len(provinces_json),
            "state_count": len(states_json),
            "ownership_pixels": own_painted,
            "total_pixels": self.static_meta["total_pixels"],
            "prime_land_count": self.static_meta["prime_land_count"],
            "normal_land_count": self.static_meta["normal_land_count"],
            "impassable_count": self.static_meta["impassable_count"],
            "incorporated_provinces": inc_prov,
            "unincorporated_provinces": uninc_prov,
            "hub_provinces": self.static_meta["hub_provinces"],
            "tag_name_count": self.static_meta["tag_name_count"],
            "state_name_count": self.static_meta["state_name_count"],
            "hub_name_count": self.static_meta["hub_name_count"],
            "culture_name_count": self.static_meta["culture_name_count"],
            "religion_name_count": self.static_meta["religion_name_count"],
            "building_name_count": self.static_meta["building_name_count"],
            "building_group_name_count": self.static_meta.get(
                "building_group_name_count",
                len(self._json_cache.get("names", {}).get("zh", {}).get("building_groups", {})),
            ),
            "pm_name_count": self.static_meta["pm_name_count"],
            "company_name_count": self.static_meta["company_name_count"],
        }

    def layer_png(self, name: str) -> bytes:
        if name not in LAYER_NAMES:
            raise KeyError(name)
        with self._lock:
            cached = self._layer_cache.get(name)
            if cached is not None:
                return cached
            if name in STATIC_LAYERS:
                stored = load_layer_png_bytes(self.conn, name)
                if stored is not None:
                    self._layer_cache[name] = stored
                    return stored
            if name != "raw":
                self._ensure_province_raster()
            if name in TERRITORY_MAIN_VIEW_LAYERS:
                self._ensure_territory_layer_rgb(name)
            rendered = self._render_layer(name)
            self._layer_cache[name] = rendered
            return rendered

    def _render_layer(self, name: str) -> bytes:
        if name in STATIC_LAYERS:
            stored = load_layer_png_bytes(self.conn, name)
            if stored is not None:
                return stored

        if name == "ownership":
            if "ownership" in self._layer_rgb:
                return self._encode_territory_layer_from_rgb("ownership")
            png_bytes, _, _ = render_ownership_png(self.model, self.conn)
            return png_bytes
        if name == "terrain":
            return render_terrain_png(self.model)
        if name == "incorporation":
            if "incorporation" in self._layer_rgb:
                return self._encode_territory_layer_from_rgb("incorporation")
            return render_incorporation_png(self.model)
        if name == "country_type":
            if "country_type" in self._layer_rgb:
                return self._encode_territory_layer_from_rgb("country_type")
            if self._tag_country_types is None:
                self._tag_country_types = load_tag_country_types(self.conn)
            return render_country_type_png(self.model, self._tag_country_types)
        if name == "homeland":
            return render_homeland_png(
                self.model,
                self.conn,
                province_geographic_state=self.static.province_geographic_state,
            )
        if name == "claims":
            return render_claims_png(
                self.model,
                self.conn,
                province_geographic_state=self.static.province_geographic_state,
            )
        if name == "foreign_investment":
            return render_foreign_investment_png(
                self.model,
                self.conn,
                province_tag_state=self.province_tag_state,
            )
        if name == "building_level":
            return render_building_level_png(
                self.model,
                self.conn,
                province_tag_state=self.province_tag_state,
            )
        if name == "slavery":
            return render_slavery_png(
                self.model,
                self.conn,
                province_tag_state=self.province_tag_state,
            )
        if name == "pop_total":
            return render_pop_total_png(
                self.model,
                self.conn,
                province_tag_state=self.province_tag_state,
            )
        if name == "pop_culture":
            return render_pop_culture_png(
                self.model,
                self.conn,
                province_tag_state=self.province_tag_state,
            )
        if name == "pop_religion":
            return render_pop_religion_png(
                self.model,
                self.conn,
                province_tag_state=self.province_tag_state,
            )
        if name == "hubs":
            return render_hubs_png(self.model)
        if name == "border_country":
            if "border_country" in self._layer_rgb:
                return self._encode_territory_layer_from_rgb("border_country")
            return render_border_country_png(self._rgb_keys, self.province_tag_state)
        if name == "raw":
            return self.png_bytes
        if name == "strategic_region":
            return render_strategic_region_png(self.model, self.conn)
        if name == "border_state":
            borders = render_border_pngs(
                self._rgb_keys,
                self.province_tag_state,
                self.static.province_geographic_state,
            )
            return borders["border_state"]
        if name == "border_province":
            borders = render_border_pngs(
                self._rgb_keys,
                self.province_tag_state,
                self.static.province_geographic_state,
            )
            return borders["border_province"]
        raise KeyError(name)

    def provinces_png(self) -> bytes:
        return self.png_bytes

    def invalidate_layers(self, *names: str) -> None:
        with self._lock:
            for name in names:
                self._layer_cache.pop(name, None)
                self._layer_rgb.pop(name, None)
            self.revision += 1
