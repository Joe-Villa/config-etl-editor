#!/usr/bin/env python3
"""Retest mods that previously had unowned_land_state errors."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from batch_build_test import ModCase, default_workers, run_case  # noqa: E402
from editor_config import MapEditorConfig, load_config  # noqa: E402

REPORT = ROOT / "output" / "batch_test" / "batch_report.json"
OUT = ROOT / "output" / "batch_test" / "unowned_retest.json"


def _worker(case: ModCase, vanilla_path: str):
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    cfg = MapEditorConfig(vanilla=Path(vanilla_path))
    return run_case(case, cfg)


def main() -> None:
    results_old = json.loads(REPORT.read_text(encoding="utf-8"))
    old_by_key: dict[tuple[str, str], dict] = {}
    for row in results_old:
        kinds = row.get("error_kinds") or {}
        unowned = kinds.get("unowned_land_state", 0)
        if unowned:
            old_by_key[(row["source"], row["name"])] = {
                "status": row["status"],
                "unowned": unowned,
                "total_errors": row.get("error_count", 0),
                "error_kinds": kinds,
                "mod_root": row["mod_root"],
            }

    cases = [
        ModCase(name=name, mod_root=Path(info["mod_root"]), source=source)
        for (source, name), info in old_by_key.items()
    ]
    config = load_config()
    vanilla = str(config.vanilla)
    workers = min(4, default_workers(len(cases)))

    new_results: dict[tuple[str, str], object] = {}
    print(f"Retesting {len(cases)} mods with {workers} workers...")
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_worker, c, vanilla): c for c in cases}
        done = 0
        for fut in as_completed(futs):
            case = futs[fut]
            result = fut.result()
            new_results[(case.source, case.name)] = result
            done += 1
            kinds = result.error_kinds or {}
            print(
                f"[{done}/{len(cases)}] {case.source}/{case.name}: "
                f"{result.status} unowned={kinds.get('unowned_land_state', 0)} "
                f"errors={result.error_count}"
            )

    rows = []
    for key, old in old_by_key.items():
        result = new_results[key]
        new_kinds = result.error_kinds or {}
        new_unowned = new_kinds.get("unowned_land_state", 0)
        rows.append(
            {
                "source": key[0],
                "name": key[1],
                "old_status": old["status"],
                "new_status": result.status,
                "old_unowned": old["unowned"],
                "new_unowned": new_unowned,
                "unowned_eliminated": old["unowned"] - new_unowned,
                "old_total_errors": old["total_errors"],
                "new_total_errors": result.error_count,
                "new_error_kinds": dict(new_kinds),
            }
        )

    rows.sort(key=lambda r: (-r["unowned_eliminated"], -r["old_unowned"]))
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    fully_cleared = [r for r in rows if r["old_unowned"] > 0 and r["new_unowned"] == 0]
    now_ok = [r for r in rows if r["old_status"] == "fail" and r["new_status"] == "ok"]
    partial = [r for r in rows if r["unowned_eliminated"] > 0 and r["new_unowned"] > 0]

    print("\n=== unowned_land_state 完全消除 ===")
    for row in fully_cleared:
        mark = " -> OK" if row["old_status"] == "fail" and row["new_status"] == "ok" else ""
        print(
            f"  {row['source']}/{row['name']}: "
            f"{row['old_unowned']} -> 0{mark} "
            f"(总错误 {row['old_total_errors']} -> {row['new_total_errors']})"
        )

    print(f"\n完全消除 unowned: {len(fully_cleared)} 个")
    print(f"原先 fail 现 ok: {len(now_ok)} 个")

    if partial:
        print("\n=== 部分消除（仍有 unowned）===")
        for row in partial:
            print(
                f"  {row['source']}/{row['name']}: "
                f"{row['old_unowned']} -> {row['new_unowned']} "
                f"(总错误 {row['old_total_errors']} -> {row['new_total_errors']})"
            )

    no_change = [r for r in rows if r["unowned_eliminated"] == 0]
    if no_change:
        print("\n=== 无改善 ===")
        for row in no_change:
            print(
                f"  {row['source']}/{row['name']}: "
                f"still {row['new_unowned']} unowned, status={row['new_status']}"
            )

    print(f"\nWritten: {OUT}")


if __name__ == "__main__":
    main()
