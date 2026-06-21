"""Tests for async country macro edit job."""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from interactive_map.macro_edit_job import MacroEditJob  # noqa: E402


class MacroEditJobTest(unittest.TestCase):
    def test_submit_and_complete(self) -> None:
        job = MacroEditJob()
        started = threading.Event()

        def runner() -> dict:
            started.set()
            time.sleep(0.05)
            return {"result": {"op": "demo"}, "revision": 7}

        body, code = job.submit(
            request_id="req-1",
            subpath="country/expand-all-split",
            runner=runner,
        )
        self.assertEqual(code, 202)
        self.assertEqual(body["status"], "accepted")
        self.assertTrue(started.wait(timeout=1.0))

        deadline = time.time() + 2.0
        while time.time() < deadline:
            snap = job.snapshot()
            if snap["phase"] == "done":
                break
            time.sleep(0.02)
        snap = job.snapshot()
        self.assertEqual(snap["phase"], "done")
        self.assertEqual(snap["result"]["op"], "demo")
        self.assertEqual(snap["revision"], 7)
        self.assertEqual(snap["progress"]["percent"], 100)

    def test_progress_updates_while_running(self) -> None:
        job = MacroEditJob()
        seen: list[int] = []
        gate = threading.Event()

        def runner() -> dict:
            job.report_progress(25, "step one", done=1, total=4)
            seen.append(job.progress_payload()["percent"])
            gate.wait(timeout=1.0)
            job.report_progress(75, "step three", done=3, total=4)
            return {"result": {"op": "demo"}, "revision": 2}

        job.submit(
            request_id="req-progress",
            subpath="country/acquire-homelands",
            runner=runner,
        )
        deadline = time.time() + 2.0
        while time.time() < deadline:
            snap = job.snapshot()
            if snap["progress"]["percent"] >= 25:
                break
            time.sleep(0.01)
        snap = job.snapshot()
        self.assertGreaterEqual(snap["progress"]["percent"], 25)
        self.assertIn("step one", snap["progress"]["message"])
        gate.set()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if job.snapshot()["phase"] == "done":
                break
            time.sleep(0.02)
        self.assertEqual(job.snapshot()["progress"]["percent"], 100)

    def test_reject_second_request_while_running(self) -> None:
        job = MacroEditJob()
        gate = threading.Event()

        def runner() -> dict:
            gate.wait(timeout=1.0)
            return {"result": {"op": "demo"}, "revision": 1}

        first, code1 = job.submit(
            request_id="req-a",
            subpath="country/acquire-homelands",
            runner=runner,
        )
        self.assertEqual(code1, 202)
        second, code2 = job.submit(
            request_id="req-b",
            subpath="country/change-tag",
            runner=lambda: {"result": {"op": "x"}, "revision": 2},
        )
        self.assertEqual(code2, 409)
        self.assertEqual(second["status"], "rejected")
        self.assertEqual(second["active"]["request_id"], "req-a")
        gate.set()

    def test_same_request_id_while_running_is_idempotent(self) -> None:
        job = MacroEditJob()
        gate = threading.Event()

        def runner() -> dict:
            gate.wait(timeout=1.0)
            return {"result": {"op": "demo"}, "revision": 3}

        job.submit(
            request_id="req-same",
            subpath="country/release-country",
            runner=runner,
        )
        again, code = job.submit(
            request_id="req-same",
            subpath="country/release-country",
            runner=runner,
        )
        self.assertEqual(code, 202)
        self.assertEqual(again["status"], "running")
        gate.set()


if __name__ == "__main__":
    unittest.main()
