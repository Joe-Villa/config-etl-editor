#!/usr/bin/env python3
"""Tkinter launcher: pick or build map_editor.sqlite after the API server starts."""

from __future__ import annotations

import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import END, filedialog, messagebox, scrolledtext, ttk

import tkinter as tk

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from interactive_map.build_job import launcher_defaults  # noqa: E402
from interactive_map.server_state import MapServerState  # noqa: E402


def _browse_dir(entry: ttk.Entry) -> None:
    path = filedialog.askdirectory()
    if path:
        entry.delete(0, END)
        entry.insert(0, path)


def _browse_sqlite(entry: ttk.Entry) -> None:
    path = filedialog.askopenfilename(
        title="选择 map_editor.sqlite",
        filetypes=[("SQLite", "*.sqlite"), ("All files", "*.*")],
    )
    if path:
        entry.delete(0, END)
        entry.insert(0, path)


def _append_log(log: scrolledtext.ScrolledText, text: str) -> None:
    log.insert(END, text)
    if not text.endswith("\n"):
        log.insert(END, "\n")
    log.see(END)


def run_launcher_gui(
    *,
    server_state: MapServerState,
    host: str,
    port: int,
) -> None:
    defaults = launcher_defaults()
    default_output = Path(defaults["output"])
    default_vanilla = defaults["vanilla"]
    package_dir = Path(defaults["cwd"])
    viewer_url = f"http://{host}:{port}/viewer/index.html"

    root = tk.Tk()
    root.title("地图编辑器")
    root.minsize(560, 520)

    status_var = tk.StringVar(value="尚未加载数据库")
    busy_var = tk.BooleanVar(value=False)

    main = ttk.Frame(root, padding=12)
    main.pack(fill=tk.BOTH, expand=True)

    ttk.Label(main, textvariable=status_var, wraplength=520).pack(anchor=tk.W, pady=(0, 8))

    open_frame = ttk.LabelFrame(main, text="打开已有数据库", padding=8)
    open_frame.pack(fill=tk.X, pady=(0, 8))

    open_entry = ttk.Entry(open_frame)
    open_entry.pack(fill=tk.X, pady=(0, 6))
    open_entry.insert(0, str(default_output))

    open_btns = ttk.Frame(open_frame)
    open_btns.pack(fill=tk.X)
    ttk.Button(open_btns, text="浏览…", command=lambda: _browse_sqlite(open_entry)).pack(
        side=tk.LEFT
    )

    build_frame = ttk.LabelFrame(main, text="从游戏内容构建数据库", padding=8)
    build_frame.pack(fill=tk.X, pady=(0, 8))

    ttk.Label(build_frame, text="Vanilla game 目录").pack(anchor=tk.W)
    vanilla_row = ttk.Frame(build_frame)
    vanilla_row.pack(fill=tk.X, pady=(0, 6))
    vanilla_entry = ttk.Entry(vanilla_row)
    vanilla_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
    vanilla_entry.insert(0, default_vanilla)
    ttk.Button(vanilla_row, text="浏览…", command=lambda: _browse_dir(vanilla_entry)).pack(
        side=tk.LEFT
    )

    ttk.Label(build_frame, text="Mod 根目录（可选，留空则仅 vanilla）").pack(anchor=tk.W)
    mod_row = ttk.Frame(build_frame)
    mod_row.pack(fill=tk.X, pady=(0, 6))
    mod_entry = ttk.Entry(mod_row)
    mod_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
    ttk.Button(mod_row, text="浏览…", command=lambda: _browse_dir(mod_entry)).pack(side=tk.LEFT)

    ttk.Label(build_frame, text="输出 sqlite 路径").pack(anchor=tk.W)
    out_row = ttk.Frame(build_frame)
    out_row.pack(fill=tk.X, pady=(0, 6))
    out_entry = ttk.Entry(out_row)
    out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
    out_entry.insert(0, str(default_output))
    ttk.Button(out_row, text="浏览…", command=lambda: _browse_sqlite(out_entry)).pack(
        side=tk.LEFT
    )

    log = scrolledtext.ScrolledText(main, height=10, state=tk.NORMAL)
    log.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

    action_row = ttk.Frame(main)
    action_row.pack(fill=tk.X)

    open_btn = ttk.Button(action_row, text="加载数据库")
    build_btn = ttk.Button(action_row, text="构建并加载")
    browser_btn = ttk.Button(action_row, text="打开浏览器")
    quit_btn = ttk.Button(action_row, text="退出")

    open_btn.pack(side=tk.LEFT, padx=(0, 6))
    build_btn.pack(side=tk.LEFT, padx=(0, 6))
    browser_btn.pack(side=tk.LEFT, padx=(0, 6))
    quit_btn.pack(side=tk.RIGHT)

    def set_busy(active: bool) -> None:
        busy_var.set(active)
        state = tk.DISABLED if active else tk.NORMAL
        open_btn.configure(state=state)
        build_btn.configure(state=state)

    def update_status(path: Path | None) -> None:
        if path is None:
            status_var.set("尚未加载数据库")
        else:
            status_var.set(f"已加载：{path}\n浏览器：{viewer_url}")

    def load_database(path: Path) -> None:
        try:
            session = server_state.load(path)
        except FileNotFoundError as exc:
            messagebox.showerror("加载失败", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("加载失败", str(exc))
            return
        update_status(path)
        _append_log(log, f"已加载 {path}（revision {session.revision}）")

    def on_open() -> None:
        raw = open_entry.get().strip()
        if not raw:
            messagebox.showwarning("提示", "请选择或输入 sqlite 路径")
            return
        load_database(Path(raw))

    def on_build() -> None:
        vanilla_raw = vanilla_entry.get().strip()
        if not vanilla_raw:
            messagebox.showwarning("提示", "请填写 vanilla game 目录")
            return
        vanilla = Path(vanilla_raw).expanduser()
        if not vanilla.is_dir():
            messagebox.showerror("路径错误", f"vanilla 目录不存在：{vanilla}")
            return

        mod_raw = mod_entry.get().strip()
        mod_root: Path | None = Path(mod_raw).expanduser() if mod_raw else None
        if mod_root is not None and not mod_root.is_dir():
            messagebox.showerror("路径错误", f"mod 目录不存在：{mod_root}")
            return

        out_raw = out_entry.get().strip() or str(default_output)
        output = Path(out_raw).expanduser().resolve()
        if output.is_file():
            messagebox.showerror(
                "构建被拒绝",
                f"输出文件已存在，拒绝覆盖：\n{output}",
            )
            return
        output.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable,
            str(package_dir / "run.py"),
            "--vanilla",
            str(vanilla),
            "-o",
            str(output),
            "--allow-errors",
        ]
        if mod_root is not None:
            cmd.append(str(mod_root))

        set_busy(True)
        _append_log(log, f"构建：{' '.join(cmd)}")

        def worker() -> None:
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=package_dir,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError as exc:
                root.after(0, lambda: finish_build(None, str(exc), None))
                return
            root.after(
                0,
                lambda: finish_build(output, proc.stdout + proc.stderr, proc.returncode),
            )

        def finish_build(output_path: Path | None, text: str, code: int | None) -> None:
            set_busy(False)
            if text.strip():
                _append_log(log, text.rstrip())
            if output_path is None:
                messagebox.showerror("构建失败", text or "未知错误")
                return
            if code != 0:
                messagebox.showerror("构建失败", f"run.py 退出码 {code}\n详见日志")
                return
            if not output_path.is_file():
                messagebox.showerror("构建失败", f"未生成文件：{output_path}")
                return
            open_entry.delete(0, END)
            open_entry.insert(0, str(output_path))
            load_database(output_path)

        threading.Thread(target=worker, daemon=True).start()

    def on_browser() -> None:
        if server_state.session is None:
            messagebox.showwarning("提示", "请先加载或构建数据库")
            return
        webbrowser.open(viewer_url)

    open_btn.configure(command=on_open)
    build_btn.configure(command=on_build)
    browser_btn.configure(command=on_browser)
    quit_btn.configure(command=root.destroy)

    ttk.Label(
        main,
        text=f"API 服务：{viewer_url}",
        foreground="#666",
    ).pack(anchor=tk.W, pady=(4, 0))

    root.mainloop()
