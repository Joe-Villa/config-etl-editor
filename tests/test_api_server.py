"""Smoke tests for api_server HTTP responses."""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.api_server import MapEditorHandler  # noqa: E402
from interactive_map.build_job import launcher_gate_defaults  # noqa: E402
from interactive_map.server_state import MapServerState  # noqa: E402

DB = ROOT / "output" / "test_map_editor.sqlite"


class ApiServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "map_db"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

        cls.server_state = MapServerState()
        cls.server_state.load(DB)
        handler = type(
            "TestMapEditorHandler",
            (MapEditorHandler,),
            {"server_state": cls.server_state},
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_state.close()

    def _get(self, path: str) -> tuple[int, bytes, dict[str, str]]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read(), dict(resp.headers)

    def test_meta_json(self) -> None:
        status, body, headers = self._get("/api/meta.json")
        self.assertEqual(status, 200)
        self.assertIn("X-Map-Revision", headers)
        meta = json.loads(body.decode("utf-8"))
        self.assertEqual(meta["width"], 8192)

    def test_viewer_html(self) -> None:
        status, body, _ = self._get("/viewer/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"/api/", body)

    def test_state_detail_json(self) -> None:
        status, body, _ = self._get(
            "/api/state-detail.json?tag=SIC&state=STATE_ABRUZZO"
        )
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["tag"], "SIC")
        self.assertIn("buildings", payload)
        self.assertIn("homelands", payload)

    def test_building_options_and_add(self) -> None:
        status, body, _ = self._get(
            "/api/edit/building-options.json?tag=SIC&state=STATE_ABRUZZO&building=building_furniture_manufactory"
        )
        self.assertEqual(status, 200)
        opts = json.loads(body.decode("utf-8"))
        self.assertGreater(len(opts["pm_groups"]), 0)

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/edit/building/add",
            data=json.dumps(
                {
                    "tag": "SIC",
                    "state": "STATE_ABRUZZO",
                    "building": "building_furniture_manufactory",
                    "level": 1,
                    "ownership_type": "country",
                    "owner_tag": "",
                    "owner_state": "",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            self.assertEqual(resp.status, 200)
            result = json.loads(resp.read().decode("utf-8"))
        bld_id = result["bld_id"]
        self.assertIn("batch_id", result)

        del_req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/edit/building/delete",
            data=json.dumps(
                {
                    "tag": "SIC",
                    "state": "STATE_ABRUZZO",
                    "bld_id": bld_id,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(del_req, timeout=60) as resp:
            self.assertEqual(resp.status, 200)

    def test_pop_options_and_add(self) -> None:
        status, body, _ = self._get(
            "/api/edit/pop-options.json?tag=SIC&state=STATE_ABRUZZO"
        )
        self.assertEqual(status, 200)
        opts = json.loads(body.decode("utf-8"))
        self.assertIn("south_italian", opts["cultures"])
        culture = opts["defaults"]["culture"]

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/edit/pop/add",
            data=json.dumps(
                {
                    "tag": "SIC",
                    "state": "STATE_ABRUZZO",
                    "culture": culture,
                    "religion": "catholic",
                    "is_slaves": False,
                    "size": 777,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            self.assertEqual(resp.status, 200)
            result = json.loads(resp.read().decode("utf-8"))
        pop_id = result["pop_id"]
        self.assertIn("batch_id", result)

        del_req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/edit/pop/delete",
            data=json.dumps(
                {
                    "tag": "SIC",
                    "state": "STATE_ABRUZZO",
                    "pop_id": pop_id,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(del_req, timeout=60) as resp:
            self.assertEqual(resp.status, 200)

    def test_export_history_json(self) -> None:
        status, body, _ = self._get("/api/export/history.json")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertIn("categories", payload)
        self.assertIn("files", payload)
        self.assertIn("BUILDINGS = {", payload["buildings"])
        self.assertIn("POPS = {", payload["pops"])
        self.assertIn("STATES = {", payload["states"])
        self.assertGreater(len(payload["files"]["buildings"]), 1)

    def test_export_edit_log_json(self) -> None:
        status, body, headers = self._get("/api/export/edit-log.json")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        payload = json.loads(body.decode("utf-8"))
        self.assertIn("batch_count", payload)
        self.assertIn("batches", payload)
        self.assertIsInstance(payload["batches"], list)

    def test_macro_job_status_idle(self) -> None:
        status, body, _ = self._get("/api/edit/macro-job.json")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["phase"], "idle")
        self.assertFalse(payload["running"])

    def test_macro_job_requires_request_id(self) -> None:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/edit/country/incorporate-all",
            data=json.dumps({"tag": "SIC"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=60)
        self.assertEqual(ctx.exception.code, 400)

    def test_export_history_zip(self) -> None:
        status, body, headers = self._get("/api/export/history.zip")
        self.assertEqual(status, 200)
        self.assertIn("application/zip", headers.get("Content-Type", ""))
        self.assertGreater(len(body), 1000)

    def test_export_layers_zip(self) -> None:
        status, body, headers = self._get("/api/export/layers.zip")
        self.assertEqual(status, 200)
        self.assertIn("application/zip", headers.get("Content-Type", ""))
        self.assertGreater(len(body), 1000)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))

        import io
        import zipfile

        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.endswith("ownership.png") for name in names))
        self.assertTrue(any(name.endswith("border_country.png") for name in names))
        self.assertTrue(any(name.endswith("border_state.png") for name in names))
        self.assertTrue(any(name.endswith("border_province.png") for name in names))

    def test_concurrent_reads(self) -> None:
        tag_row = self.server_state.session.conn.execute(
            """
            SELECT tag FROM st_prov
            GROUP BY tag
            ORDER BY COUNT(*) DESC
            LIMIT 1
            """
        ).fetchone()
        self.assertIsNotNone(tag_row)
        tag = str(tag_row[0])

        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def reader() -> None:
            try:
                barrier.wait(timeout=30)
                for _ in range(25):
                    status, _, _ = self._get(
                        f"/api/edit/country-macro.json?tag={tag}"
                    )
                    self.assertIn(status, (200, 400))
                    status, _, _ = self._get("/api/meta.json")
                    self.assertEqual(status, 200)
                    status, _, _ = self._get("/api/states.json")
                    self.assertEqual(status, 200)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        workers = [threading.Thread(target=reader, daemon=True) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=120)

        self.assertEqual(errors, [], errors)

    def test_atomic_map_bootstrap(self) -> None:
        status, body, headers = self._get("/api/atomic/map-bootstrap.json")
        self.assertEqual(status, 200)
        self.assertIn("X-Map-Revision", headers)
        payload = json.loads(body.decode("utf-8"))
        for key in (
            "revision",
            "meta",
            "terrain",
            "names",
            "homeland",
            "provinces",
            "states",
            "countries",
            "incorporation",
        ):
            self.assertIn(key, payload, msg=key)
        self.assertGreater(payload["meta"]["province_count"], 0)
        self.assertEqual(payload.get("active_view_layer"), "ownership")
        self.assertNotIn("foreign_investment", payload)
        self.assertNotIn("slavery", payload)
        self.assertNotIn("pop_total", payload)

    def test_atomic_layer_data_lazy(self) -> None:
        status, body, _ = self._get(
            "/api/atomic/layer-data.json?layer=foreign_investment"
        )
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["layer"], "foreign_investment")
        self.assertIn("by_scope", payload["data"])
        self.assertIn("legend", payload["data"])

    def test_atomic_refresh_dynamic_layer(self) -> None:
        _, body, headers = self._get("/api/atomic/map-bootstrap.json")
        bootstrap = json.loads(body.decode("utf-8"))
        self.assertEqual(bootstrap["view_layer_types"]["terrain"], "static")
        self.assertEqual(bootstrap["view_layer_types"]["ownership"], "dynamic")

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/atomic/refresh-layer.json",
            data=json.dumps({"layer": "ownership"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("X-Map-Revision", dict(resp.headers))
            payload = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(payload["layer"], "ownership")
        self.assertIn("revision", payload)
        self.assertNotIn("data", payload)

        bad_req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/atomic/refresh-layer.json",
            data=json.dumps({"layer": "terrain"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(bad_req, timeout=60)
        self.assertEqual(ctx.exception.code, 400)

    def test_atomic_country_panel(self) -> None:
        status, body, _ = self._get("/api/atomic/country-panel.json?tag=SIC")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["tag"], "SIC")
        self.assertIn("macro_preview", payload)
        self.assertIn("transfer_options", payload)
        self.assertIn("tags", payload["transfer_options"])

    def test_state_type_edit_includes_view_patch(self) -> None:
        _, body, _ = self._get("/api/states.json")
        states = json.loads(body.decode("utf-8"))
        info = states["SIC::STATE_APULIA"]
        next_type = (
            "unincorporated"
            if info["state_type"] == "incorporated"
            else "incorporated"
        )
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/edit/state/type",
            data=json.dumps(
                {
                    "tag": "SIC",
                    "state": "STATE_APULIA",
                    "state_type": next_type,
                    "view_layer": "ownership",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            self.assertEqual(resp.status, 200)
            result = json.loads(resp.read().decode("utf-8"))
        patch = result.get("view_patch")
        self.assertIsInstance(patch, dict)
        self.assertIn("provinces", patch)
        self.assertIn("states", patch)
        self.assertIn("layer_patches", patch)
        self.assertIn("ownership", patch["layer_patches"])
        self.assertIn("png_b64", patch["layer_patches"]["ownership"])
        self.assertIn("ownership", patch.get("layers", []))
        self.assertIn("border_country", patch.get("layers", []))

    def test_db_snapshot_save_list_restore(self) -> None:
        from interactive_map.db_snapshot import create_snapshot  # noqa: WPS433

        create_snapshot(DB, label="api-test-baseline")

        status, body, _ = self._get("/api/db-snapshots.json")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertGreaterEqual(len(payload["snapshots"]), 1)

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/db-snapshot/save",
            data=json.dumps({"label": "api-test-save"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            self.assertEqual(resp.status, 200)
            saved = json.loads(resp.read().decode("utf-8"))
        snapshot_id = saved["snapshot"]["id"]

        add_req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/edit/pop/add",
            data=json.dumps(
                {
                    "tag": "SIC",
                    "state": "STATE_ABRUZZO",
                    "culture": "south_italian",
                    "religion": "catholic",
                    "is_slaves": False,
                    "size": 1234,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(add_req, timeout=60) as resp:
                self.assertEqual(resp.status, 200)
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise

        restore_req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/db-snapshot/restore",
            data=json.dumps({"id": snapshot_id}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(restore_req, timeout=120) as resp:
            self.assertEqual(resp.status, 200)
            restored = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(restored["snapshot"]["id"], snapshot_id)
        self.assertIn("revision", restored)


class ApiServerUnloadedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DB.is_file():
            src = ROOT / "map_db"
            if str(src) not in sys.path:
                sys.path.insert(0, str(src))
            from build_db import build_map_db  # noqa: E402
            from editor_config import load_config  # noqa: E402

            build_map_db(load_config().vanilla, DB, load_config(), fail_on_error=True)

        cls.server_state = MapServerState()
        handler = type(
            "TestMapEditorUnloadedHandler",
            (MapEditorHandler,),
            {"server_state": cls.server_state},
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_state.close()

    def setUp(self) -> None:
        with self.server_state._lock:
            if self.server_state._session is not None:
                self.server_state._session.close()
                self.server_state._session = None

    def _get(self, path: str) -> tuple[int, bytes, dict[str, str]]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read(), dict(resp.headers)

    def _get_error(self, path: str) -> tuple[int, str]:
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def test_status_unloaded(self) -> None:
        status, body, _ = self._get("/api/status.json")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertFalse(payload["loaded"])
        self.assertIsNone(payload["database"])
        self.assertIn("defaults", payload)
        self.assertIn("build", payload)

    def test_status_defaults_paths(self) -> None:
        status, body, _ = self._get("/api/status.json")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        expected = launcher_gate_defaults()
        self.assertEqual(payload["defaults"]["output"], expected["output"])
        self.assertEqual(payload["defaults"]["vanilla"], expected["vanilla"])
        self.assertEqual(payload["defaults"]["cwd"], expected["cwd"])
        self.assertIn("Victoria 3", payload["defaults"]["vanilla"])

    def test_build_database_rejects_existing_output(self) -> None:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/build-database",
            data=json.dumps({"output": str(DB)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=60)
        self.assertEqual(ctx.exception.code, 409)
        message = ctx.exception.read().decode("utf-8")
        self.assertIn("已存在", message)

    def test_meta_requires_database(self) -> None:
        status, message = self._get_error("/api/meta.json")
        self.assertEqual(status, 503)
        self.assertIn("尚未加载数据库", message)

    def test_load_database(self) -> None:
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/load-database",
            data=json.dumps({"path": str(DB)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            self.assertEqual(resp.status, 200)
            payload = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(payload["database"], str(DB.resolve()))

        status, body, _ = self._get("/api/status.json")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["loaded"])
        self.assertEqual(payload["database"], str(DB.resolve()))


if __name__ == "__main__":
    unittest.main()
