"""Control-layer read models: one user-facing query → one atomic bundle."""

from __future__ import annotations

from interactive_map.country_type_layer import build_country_type_json
from interactive_map.data.homeland_repo import load_all_geo_states, load_state_cultures_map
from interactive_map.data.sql_session import SqlSession
from interactive_map.building_levels import build_building_level_json
from interactive_map.claim_layer import build_claims_json
from interactive_map.foreign_investment import build_foreign_investment_json
from interactive_map.homeland_layer import HOMELAND_LABEL_MULTI, HOMELAND_LABEL_NONE
from interactive_map.hubs import build_hubs_json
from interactive_map.incremental_layers import (
    DATA_DRIVEN_VIEW_LAYERS,
    DYNAMIC_VIEW_LAYERS,
    TERRITORY_MAIN_VIEW_LAYERS,
    view_layer_types,
)
from interactive_map.map_session import MapSession
from interactive_map.palette import HOMELAND_MULTI_RGB, HOMELAND_NONE_RGB
from interactive_map.pop_layers import (
    build_pop_culture_json,
    build_pop_religion_json,
    build_pop_total_json,
    build_slavery_json,
)
from interactive_map.incorporation import build_incorporation_json
from interactive_map.db_reader import (
    load_countries_json,
    load_provinces_json,
    load_states_json,
)
from interactive_map.edit.transfer import load_country_macro_preview, load_transfer_options
from interactive_map.strategic_regions import load_strategic_regions_json
from interactive_map.annotate import build_terrain_json


class ViewService:
    """Compose view bundles from data layer + existing render helpers."""

    @staticmethod
    def homeland_json(conn) -> dict:
        sql = SqlSession(conn)
        state_homelands = load_state_cultures_map(sql)
        all_geo_states = load_all_geo_states(sql)
        states_with_homeland = set(state_homelands)
        return {
            "state_homelands": state_homelands,
            "colors": {
                "none": list(HOMELAND_NONE_RGB),
                "multi": list(HOMELAND_MULTI_RGB),
            },
            "stats": {
                "single_culture_states": sum(
                    1 for homelands in state_homelands.values() if len(homelands) == 1
                ),
                "multi_culture_states": sum(
                    1 for homelands in state_homelands.values() if len(homelands) > 1
                ),
                "no_homeland_states": len(all_geo_states - states_with_homeland),
            },
        }

    @classmethod
    def map_bootstrap(cls, session: MapSession) -> dict:
        """Single atomic read for initial map load (default ownership view only)."""
        conn = session.conn
        geographic_model = session.geographic_model_for_json()
        return {
            "revision": session.revision,
            "meta": session.meta_json(),
            "terrain": build_terrain_json(geographic_model),
            "names": session.json_document("names"),
            "strategic_regions": load_strategic_regions_json(conn),
            "homeland": cls.homeland_json(conn),
            "country_type": build_country_type_json(conn),
            "hubs": build_hubs_json(geographic_model),
            "provinces": load_provinces_json(conn),
            "states": load_states_json(conn),
            "countries": load_countries_json(conn),
            "incorporation": build_incorporation_json(conn),
            "active_view_layer": "ownership",
            "view_layer_types": view_layer_types(),
        }

    @staticmethod
    def country_panel(conn, tag: str) -> dict:
        """Single atomic read for country macro side panel."""
        tag = str(tag)
        preview = load_country_macro_preview(conn, tag)
        transfer_options = load_transfer_options(conn)
        return {
            "tag": tag,
            "macro_preview": preview,
            "transfer_options": transfer_options,
        }

    @classmethod
    def _attach_data_driven_layer(
        cls,
        payload: dict,
        session: MapSession,
        view_layer: str | None,
    ) -> None:
        if view_layer not in DATA_DRIVEN_VIEW_LAYERS:
            return
        conn = session.conn
        layers = payload.setdefault("layers", [])
        if view_layer not in layers:
            layers.append(view_layer)
        if view_layer == "foreign_investment":
            payload["foreign_investment"] = build_foreign_investment_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        elif view_layer == "building_level":
            payload["building_level"] = build_building_level_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        elif view_layer == "slavery":
            payload["slavery"] = build_slavery_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        elif view_layer == "pop_total":
            payload["pop_total"] = build_pop_total_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        elif view_layer == "pop_culture":
            payload["pop_culture"] = build_pop_culture_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        elif view_layer == "pop_religion":
            payload["pop_religion"] = build_pop_religion_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        elif view_layer == "homeland":
            payload["homeland"] = cls.homeland_json(conn)
        elif view_layer == "claims":
            payload["claims"] = build_claims_json(conn)

    @classmethod
    def territory_view_patch(
        cls,
        session: MapSession,
        revision: int,
        *,
        view_layer: str | None = None,
    ) -> dict:
        """Single atomic read after territory-changing edits — one frontend update."""
        conn = session.conn
        layer_patches = session.take_territory_patches_for_view()
        reload_layers: list[str] = []
        for name in TERRITORY_MAIN_VIEW_LAYERS:
            if name in layer_patches:
                reload_layers.append(name)
        if "border_country" in layer_patches and "border_country" not in reload_layers:
            reload_layers.append("border_country")
        if not reload_layers:
            main = (
                view_layer
                if view_layer in TERRITORY_MAIN_VIEW_LAYERS
                else "ownership"
            )
            reload_layers.extend([main, "border_country"])
        payload: dict = {
            "revision": revision,
            "provinces": load_provinces_json(conn),
            "states": load_states_json(conn),
            "countries": load_countries_json(conn),
            "incorporation": build_incorporation_json(conn),
            "layer_patches": layer_patches,
            "layers": reload_layers,
            "view_layer": view_layer,
        }
        cls._attach_data_driven_layer(payload, session, view_layer)
        return payload

    @classmethod
    def homeland_view_patch(
        cls,
        session: MapSession,
        revision: int,
        *,
        view_layer: str | None = None,
    ) -> dict:
        payload: dict = {
            "revision": revision,
            "layers": [],
            "view_layer": view_layer,
        }
        cls._attach_data_driven_layer(payload, session, view_layer)
        return payload

    @classmethod
    def scope_data_view_patch(
        cls,
        session: MapSession,
        revision: int,
        *,
        view_layer: str | None = None,
    ) -> dict:
        payload: dict = {
            "revision": revision,
            "layers": [],
            "view_layer": view_layer,
        }
        cls._attach_data_driven_layer(payload, session, view_layer)
        return payload

    @classmethod
    def lazy_layer_json(cls, session: MapSession, layer: str) -> dict:
        """Load JSON backing a data-driven view layer on first activation."""
        conn = session.conn
        if layer == "foreign_investment":
            return build_foreign_investment_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        if layer == "building_level":
            return build_building_level_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        if layer == "slavery":
            return build_slavery_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        if layer == "pop_total":
            return build_pop_total_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        if layer == "pop_culture":
            return build_pop_culture_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        if layer == "pop_religion":
            return build_pop_religion_json(
                conn,
                province_tag_state=session.province_tag_state,
            )
        if layer == "homeland":
            return cls.homeland_json(conn)
        if layer == "claims":
            return build_claims_json(conn)
        raise KeyError(layer)

    @classmethod
    def refresh_view_layer(cls, session: MapSession, layer: str) -> dict:
        """Recompute one dynamic view layer from sqlite; discard server-side caches."""
        if layer not in DYNAMIC_VIEW_LAYERS:
            raise ValueError(f"未知或非动态视图图层：{layer}")
        revision = session.refresh_view_layer(layer)
        payload: dict = {"layer": layer, "revision": revision}
        if layer in DATA_DRIVEN_VIEW_LAYERS:
            payload["data"] = cls.lazy_layer_json(session, layer)
        return payload
