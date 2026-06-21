#!/usr/bin/env python3
"""Retest mods that previously crashed in batch_build_test."""

from __future__ import annotations

import json
import sys
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from batch_build_test import (  # noqa: E402
    GAMEBASE,
    ModCase,
    WORKSHOP,
    run_case,
    safe_db_name,
)
from editor_config import load_config  # noqa: E402

PREV_CRASH_WORKSHOP = [
    "2880120246", "2893069455", "2897829235", "2899755504", "2902419191",
    "2923418734", "2927730563", "2941620709", "2947324654", "2953480221",
    "2962039210", "2962076252", "3118003368", "3140199800", "3163250711",
    "3163487770", "3198162281", "3219394272", "3235838636", "3259521827",
    "3260268786", "3279217222", "3313827020", "3337303984", "3371693463",
    "3579741601", "3583668953", "3664275484", "3683677966",
]
PREV_CRASH_GAMEBASE = ["MNAR"]

# README2 额外提到的曾 crash 模组名（gamebase 文件夹名）
README_GAMEBASE_HINTS = [
    "Realism Ai",
    "vtuber时代",
    "Age of Discovery 1444",
    "Times of Victory 1648",
    "Divergences of Darkness",
    "关山万里加强版",
    "Victorian Century",
    "TIMELESS_ECHOES",
    "1648",
    "TNO dev",
    "AD 1648",
    "Beyond Rice and Salt",
    "Modern World",
    "Basileia Romaion",
    "天朝之乱",
    "Age Of Ming",
    "Anbennar",
    "The Pony In The High Castle",
]


def collect_cases() -> list[ModCase]:
    cases: list[ModCase] = []
    for name in PREV_CRASH_GAMEBASE:
        p = GAMEBASE / name
        if p.is_dir():
            cases.append(ModCase(name, p, "gamebase"))
    if GAMEBASE.is_dir():
        lower_hints = {h.lower(): h for h in README_GAMEBASE_HINTS}
        for child in GAMEBASE.iterdir():
            if child.name in PREV_CRASH_GAMEBASE:
                continue
            key = child.name.lower()
            if key in lower_hints or any(h.lower() in key for h in README_GAMEBASE_HINTS):
                cases.append(ModCase(child.name, child, "gamebase"))
    for wid in PREV_CRASH_WORKSHOP:
        p = WORKSHOP / wid
        if p.is_dir():
            cases.append(ModCase(wid, p, "workshop"))
    return cases


def worker(case: ModCase, vanilla: str) -> dict:
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    from editor_config import MapEditorConfig

    config = MapEditorConfig(vanilla=Path(vanilla))
    r = run_case(ModCase(case.name, case.mod_root, case.source), config)
    return {
        "name": r.name,
        "source": r.source,
        "status": r.status,
        "exception": r.exception,
        "error_count": r.error_count,
        "errors_sample": r.errors[:2],
    }


if __name__ == "__main__":
    # Patch OUT_DIR for this run
    import batch_build_test as bbt

    out_dir = ROOT / "output" / "batch_test_retest"
    out_dir.mkdir(parents=True, exist_ok=True)
    bbt.OUT_DIR = out_dir

    config = load_config()
    cases = collect_cases()
    print(f"Retesting {len(cases)} mods...")

    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(worker, c, str(config.vanilla)): c for c in cases}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:
                r = {
                    "name": c.name,
                    "source": c.source,
                    "status": "crash",
                    "exception": f"{type(exc).__name__}: {exc}",
                    "error_count": 0,
                    "errors_sample": [traceback.format_exc()],
                }
            results.append(r)
            print(f"{r['status']:5} {r['source']}/{r['name']} {r.get('exception') or ''}")

    by_status: dict[str, list] = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r)

    report_lines = [
        f"Retest {len(results)} previously-crashing mods",
        f"ok={len(by_status.get('ok', []))} fail={len(by_status.get('fail', []))} "
        f"crash={len(by_status.get('crash', []))} skip={len(by_status.get('skip', []))}",
        "",
    ]
    if by_status.get("crash"):
        report_lines.append("--- STILL CRASH ---")
        for r in sorted(by_status["crash"], key=lambda x: (x["source"], x["name"])):
            report_lines.append(f"  {r['source']}/{r['name']}: {r['exception']}")
            for e in r.get("errors_sample", [])[:1]:
                report_lines.append(f"    {e.splitlines()[-1][:200]}")
    if by_status.get("fail"):
        report_lines.append("--- NOW FAIL (import errors) ---")
        for r in sorted(by_status["fail"], key=lambda x: -x["error_count"]):
            report_lines.append(
                f"  {r['source']}/{r['name']}: {r['error_count']} errors — {r['exception']}"
            )
            for e in r.get("errors_sample", [])[:1]:
                report_lines.append(f"    {e[:150]}")

    text = "\n".join(report_lines)
    print("\n" + text)
    out_dir.joinpath("retest_report.txt").write_text(text, encoding="utf-8")
    out_dir.joinpath("retest_report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
