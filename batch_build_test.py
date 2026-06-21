#!/usr/bin/env python3
"""Batch test: build map editor sqlite for vanilla + mods from gamebase & workshop."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import traceback
from contextlib import redirect_stdout
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_db import BuildMapDbError, build_map_db, resolve_build_output_path  # noqa: E402
from editor_config import MapEditorConfig, load_config  # noqa: E402

GAMEBASE = Path("/home/liulingda/桌面/vic3modder/gamebase")
WORKSHOP = Path(
    "/home/liulingda/.steam/debian-installation/steamapps/workshop/content/529340"
)
OUT_DIR = ROOT / "output" / "batch_test"
REPORT_JSON = OUT_DIR / "batch_report.json"
REPORT_TXT = OUT_DIR / "batch_report.txt"

ERROR_PATTERNS = {
    "undefined_tag": re.compile(r"ownership .+：未定义的 tag"),
    "unknown_state": re.compile(r"ownership .+：未知 state"),
    "unowned_land_state": re.compile(r"陆地州 .+ 未被任何 tag 拥有"),
    "province_multi_state_region": re.compile(
        r"province .+：同时属于 .+（map_data/state_regions）"
    ),
    "country_definition_parse": re.compile(r"解析国家定义块"),
}

WARNING_CATEGORIES = {
    "state_region_province": re.compile(r"state_region .+ 不应该拥有 province"),
    "province_map_states_mismatch": re.compile(
        r"(province .+：history/states 归属 .+ 与 map_data .+ 不一致，已按 map_data 改为|"
        r".+ province .+：history/states 归属 .+ 与 map_data .+ 不一致，已按 map_data 改为)"
    ),
    "culture_religion": re.compile(r"文化 .+：默认宗教"),
    "homeland": re.compile(r"homeland"),
    "claim": re.compile(r"claim"),
    "province": re.compile(r"province"),
    "pop": re.compile(r"^pop "),
    "building": re.compile(r"^building |^建筑 "),
    "state_meta": re.compile(r"state_meta"),
    "unowned_province_assign": re.compile(r"province .+未被认领"),
    "bg_bld_ref": re.compile(r"建筑 building_|未知建筑组|未知 PM 组"),
    "pops_no_state": re.compile(r"pops .+：在 states 中不存在"),
    "duplicate": re.compile(r"重复"),
    "pop_duplicate": re.compile(r"重复人口"),
    "pop_invalid_size": re.compile(r"size=.*小于 1"),
    "st_duplicate": re.compile(r"重复 create_state"),
    "reserves": re.compile(r"reserves="),
    "pm": re.compile(r"PM"),
}


@dataclass
class ModCase:
    name: str
    mod_root: Path
    source: str


@dataclass
class BuildResult:
    name: str
    source: str
    mod_root: str
    status: str  # ok | fail | skip | crash
    error_count: int = 0
    warning_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_kinds: dict[str, int] = field(default_factory=dict)
    warning_kinds: dict[str, int] = field(default_factory=dict)
    exception: str | None = None
    output_path: str | None = None
    has_common_history: bool = False


def has_common_history(path: Path) -> bool:
    return path.is_dir() and (path / "common" / "history").is_dir()


def collect_cases(config_vanilla: Path) -> list[ModCase]:
    cases: list[ModCase] = []
    cases.append(ModCase("vanilla", config_vanilla, "vanilla"))

    if GAMEBASE.is_dir():
        for child in sorted(GAMEBASE.iterdir(), key=lambda p: p.name.lower()):
            if child.name.endswith(".mod"):
                continue
            if child.is_dir():
                cases.append(ModCase(child.name, child, "gamebase"))

    if WORKSHOP.is_dir():
        for child in sorted(WORKSHOP.iterdir(), key=lambda p: p.name):
            if child.is_dir():
                cases.append(ModCase(child.name, child, "workshop"))

    return cases


def classify_errors(errors: list[str]) -> dict[str, int]:
    kinds: Counter[str] = Counter()
    for msg in errors:
        matched = False
        for kind, pat in ERROR_PATTERNS.items():
            if pat.search(msg):
                kinds[kind] += 1
                matched = True
                break
        if not matched:
            kinds["other"] += 1
    return dict(kinds)


def classify_warnings(warnings: list[str]) -> dict[str, int]:
    kinds: Counter[str] = Counter()
    for msg in warnings:
        matched = False
        for kind, pat in WARNING_CATEGORIES.items():
            if pat.search(msg):
                kinds[kind] += 1
                matched = True
                break
        if not matched:
            kinds["other"] += 1
    return dict(kinds)


def safe_db_name(name: str) -> str:
    # Keep folder name; only replace chars unsafe for filenames.
    return re.sub(r'[<>:"/\\|?*]', "_", name)


def run_case(case: ModCase, config, *, skip_map_images: bool) -> BuildResult:
    result = BuildResult(
        name=case.name,
        source=case.source,
        mod_root=str(case.mod_root),
        status="skip",
        has_common_history=has_common_history(case.mod_root),
    )
    if case.source != "vanilla" and not result.has_common_history:
        result.exception = "无 common/history/ 目录，跳过建库"
        return result

    base_path = OUT_DIR / f"{safe_db_name(case.name)}.sqlite"
    result.output_path = str(
        resolve_build_output_path(base_path, skip_map_images=skip_map_images)
    )

    try:
        log = build_map_db(
            case.mod_root,
            base_path,
            config,
            fail_on_error=True,
            skip_map_images=skip_map_images,
        )
        result.status = "ok"
        result.error_count = len(log.errors)
        result.warning_count = len(log.warnings)
        result.errors = list(log.errors)
        result.warnings = list(log.warnings)
    except BuildMapDbError as exc:
        result.status = "fail"
        result.exception = str(exc)
        result.errors = list(exc.log.errors)
        result.warnings = list(exc.log.warnings)
        result.error_count = len(result.errors)
        result.warning_count = len(result.warnings)
    except Exception as exc:
        result.status = "crash"
        result.exception = f"{type(exc).__name__}: {exc}"
        result.errors = [traceback.format_exc()]

    result.error_kinds = classify_errors(result.errors)
    result.warning_kinds = classify_warnings(result.warnings)
    return result


def _run_case_worker(case: ModCase, vanilla_path: str, skip_map_images: bool) -> BuildResult:
    """ProcessPool worker: rebuild import path in child process."""
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))
    config = MapEditorConfig(vanilla=Path(vanilla_path))
    with redirect_stdout(io.StringIO()):
        return run_case(case, config, skip_map_images=skip_map_images)


def default_workers(case_count: int) -> int:
    """Parallelism safe for ~30GB RAM: each worker loads full game defs."""
    cpu = os.cpu_count() or 4
    return max(1, min(8, cpu, case_count))


def summarize(results: list[BuildResult]) -> str:
    lines: list[str] = []
    by_status = Counter(r.status for r in results)
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    for r in results:
        by_source[r.source][r.status] += 1

    lines.append("=" * 72)
    lines.append(f"批量建库测试  {datetime.now(timezone.utc).isoformat()}")
    lines.append("=" * 72)
    lines.append(f"总计 {len(results)} 个用例")
    lines.append(
        f"  成功 ok: {by_status['ok']}  失败 fail: {by_status['fail']}  "
        f"跳过 skip: {by_status['skip']}  崩溃 crash: {by_status['crash']}"
    )
    lines.append("")
    for source in ("vanilla", "gamebase", "workshop"):
        c = by_source.get(source, Counter())
        total = sum(c.values())
        if total:
            lines.append(
                f"[{source}] {total} 个: ok={c['ok']} fail={c['fail']} "
                f"skip={c['skip']} crash={c['crash']}"
            )
    lines.append("")

    # Failure analysis
    fails = [r for r in results if r.status == "fail"]
    if fails:
        lines.append("--- 失败用例 ---")
        fail_error_kinds: Counter[str] = Counter()
        for r in fails:
            lines.append(f"  {r.source}/{r.name}: {r.error_count} errors")
            if r.exception:
                lines.append(f"    exception: {r.exception}")
            for kind, n in sorted(r.error_kinds.items()):
                fail_error_kinds[kind] += n
                if n <= 3:
                    sample = [e for e in r.errors if ERROR_PATTERNS.get(kind, re.compile("")).search(e) or kind == "other"][:2]
                else:
                    sample = []
            for kind, n in sorted(r.error_kinds.items()):
                lines.append(f"    {kind}: {n}")
        lines.append("")
        lines.append("失败错误类型汇总（跨用例计数）：")
        for kind, n in fail_error_kinds.most_common():
            lines.append(f"  {kind}: {n}")
        lines.append("")

    skips = [r for r in results if r.status == "skip"]
    if skips:
        lines.append("--- 跳过（无 common/history/）---")
        for r in skips:
            lines.append(f"  {r.source}/{r.name}")
        lines.append("")

    crashes = [r for r in results if r.status == "crash"]
    if crashes:
        lines.append("--- 崩溃 ---")
        for r in crashes:
            lines.append(f"  {r.source}/{r.name}: {r.exception}")
        lines.append("")

    # Success warnings
    oks = [r for r in results if r.status == "ok"]
    oks_with_warn = [r for r in oks if r.warning_count > 0]
    lines.append(f"--- 成功但有 warning 的用例: {len(oks_with_warn)}/{len(oks)} ---")
    if oks_with_warn:
        warn_kinds_all: Counter[str] = Counter()
        for r in oks_with_warn:
            for kind, n in r.warning_kinds.items():
                warn_kinds_all[kind] += n
        lines.append("成功用例 warning 类型汇总：")
        for kind, n in warn_kinds_all.most_common():
            lines.append(f"  {kind}: {n}")

        # Vanilla baseline
        vanilla = next((r for r in results if r.name == "vanilla"), None)
        vanilla_warn_kinds = set(vanilla.warning_kinds.keys()) if vanilla else set()

        unexpected: list[BuildResult] = []
        for r in oks_with_warn:
            if r.name == "vanilla":
                continue
            extra_kinds = set(r.warning_kinds.keys()) - vanilla_warn_kinds - {"other"}
            if extra_kinds or r.warning_count > (vanilla.warning_count * 2 + 10):
                unexpected.append(r)

        lines.append("")
        lines.append(
            f"相对 vanilla 可能异常的 warning（新类型或数量远超 vanilla）: {len(unexpected)} 个"
        )
        for r in sorted(unexpected, key=lambda x: -x.warning_count)[:30]:
            extra = set(r.warning_kinds.keys()) - vanilla_warn_kinds
            lines.append(
                f"  {r.source}/{r.name}: {r.warning_count} warnings, "
                f"kinds={r.warning_kinds}, extra_vs_vanilla={sorted(extra)}"
            )
        if len(unexpected) > 30:
            lines.append(f"  ... 另有 {len(unexpected) - 30} 个")

    lines.append("")
    lines.append("--- 全部失败/跳过明细 ---")
    for r in results:
        if r.status in ("fail", "skip", "crash"):
            lines.append(f"{r.status:5} {r.source:8} {r.name}")
            if r.errors[:3]:
                for e in r.errors[:3]:
                    lines.append(f"       {e[:120]}")
            if r.exception and r.status != "fail":
                lines.append(f"       {r.exception}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="并行批量建库测试")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="并行进程数；0 表示 min(8, CPU 核数)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="开始前删除 output/batch_test 下已有 .sqlite",
    )
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="仅重试上次 batch_report.json 中 status=fail 且仍存在的模组",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        default=REPORT_JSON,
        help="读取/写入报告 JSON 路径",
    )
    parser.add_argument(
        "--report-txt",
        type=Path,
        default=REPORT_TXT,
        help="写入报告 TXT 路径",
    )
    parser.add_argument(
        "--skip-map-images",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="跳过地图图片计算（默认开启；输出文件名前加 test）",
    )
    args = parser.parse_args()

    config = load_config()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for old in OUT_DIR.glob("*.sqlite"):
            old.unlink()

    cases = collect_cases(config.vanilla)
    if args.retry_failures:
        if not args.report_json.is_file():
            print(f"未找到失败报告: {args.report_json}", file=sys.stderr)
            sys.exit(1)
        prev = json.loads(args.report_json.read_text(encoding="utf-8"))
        fail_keys = {
            (r["source"], r["name"])
            for r in prev
            if r.get("status") == "fail"
        }
        cases = [c for c in cases if (c.source, c.name) in fail_keys]
        missing = fail_keys - {(c.source, c.name) for c in cases}
        if missing:
            print(f"已删除/不可用，跳过 {len(missing)} 个曾失败模组")
        print(f"重试曾失败模组: {len(cases)} 个")
        args.report_txt = OUT_DIR / "batch_retry_report.txt"
        args.report_json = OUT_DIR / "batch_retry_report.json"
    workers = args.workers if args.workers > 0 else default_workers(len(cases))
    workers = min(workers, len(cases))

    print(f"vanilla path: {config.vanilla}")
    print(f"cases: {len(cases)} (gamebase+workshop+vanilla)")
    print(f"output dir: {OUT_DIR}")
    print(f"parallel workers: {workers}")
    print(f"skip map images: {args.skip_map_images}")

    results: list[BuildResult] = []
    vanilla_str = str(config.vanilla)
    done = 0
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_run_case_worker, case, vanilla_str, args.skip_map_images): case
            for case in cases
        }
        for fut in as_completed(futures):
            case = futures[fut]
            done += 1
            try:
                result = fut.result()
            except Exception as exc:
                result = BuildResult(
                    name=case.name,
                    source=case.source,
                    mod_root=str(case.mod_root),
                    status="crash",
                    exception=f"{type(exc).__name__}: {exc}",
                    errors=[traceback.format_exc()],
                )
            results.append(result)
            extra = f" ({result.exception})" if result.exception and result.status != "ok" else ""
            print(
                f"[{done}/{len(cases)}] {result.status:5} "
                f"{case.source}/{case.name} "
                f"errors={result.error_count} warnings={result.warning_count}{extra}",
                flush=True,
            )

    results.sort(key=lambda r: (r.source, r.name))

    report = summarize(results)
    print(report)

    args.report_txt.write_text(report, encoding="utf-8")
    args.report_json.write_text(
        json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n报告已写入: {args.report_txt}")
    print(f"JSON: {args.report_json}")


if __name__ == "__main__":
    main()
