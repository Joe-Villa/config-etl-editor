"""Tkinter launcher: open map_editor.sqlite and use the web editor (no database build)."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from tkinter import END, filedialog, messagebox, scrolledtext, ttk

import tkinter as tk

_PKG = Path(__file__).resolve().parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from app_paths import default_save_sqlite, package_root
from interactive_map.server_state import MapServerState

ROOT = package_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


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


def run_viewer_launcher_gui(
    *,
    server_state: MapServerState,
    host: str,
    port: int,
) -> None:
    default_output = default_save_sqlite()
    viewer_url = f"http://{host}:{port}/viewer/index.html"

    root = tk.Tk()
    root.title("地图编辑器")
    root.minsize(480, 360)

    status_var = tk.StringVar(value="尚未加载数据库")

    main = ttk.Frame(root, padding=12)
    main.pack(fill=tk.BOTH, expand=True)

    ttk.Label(main, textvariable=status_var, wraplength=440).pack(anchor=tk.W, pady=(0, 8))

    open_frame = ttk.LabelFrame(main, text="打开数据库", padding=8)
    open_frame.pack(fill=tk.X, pady=(0, 8))

    open_entry = ttk.Entry(open_frame)
    open_entry.pack(fill=tk.X, pady=(0, 6))
    if default_output.is_file():
        open_entry.insert(0, str(default_output))

    open_btns = ttk.Frame(open_frame)
    open_btns.pack(fill=tk.X)
    ttk.Button(open_btns, text="浏览…", command=lambda: _browse_sqlite(open_entry)).pack(
        side=tk.LEFT
    )

    log = scrolledtext.ScrolledText(main, height=8, state=tk.NORMAL)
    log.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

    action_row = ttk.Frame(main)
    action_row.pack(fill=tk.X)

    open_btn = ttk.Button(action_row, text="加载数据库")
    browser_btn = ttk.Button(action_row, text="打开浏览器")
    quit_btn = ttk.Button(action_row, text="退出")

    open_btn.pack(side=tk.LEFT, padx=(0, 6))
    browser_btn.pack(side=tk.LEFT, padx=(0, 6))
    quit_btn.pack(side=tk.RIGHT)

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

    def on_browser() -> None:
        if server_state.session is None:
            messagebox.showwarning("提示", "请先加载数据库")
            return
        webbrowser.open(viewer_url)

    open_btn.configure(command=on_open)
    browser_btn.configure(command=on_browser)
    quit_btn.configure(command=root.destroy)

    ttk.Label(
        main,
        text=f"API 服务：{viewer_url}",
        foreground="#666",
    ).pack(anchor=tk.W, pady=(4, 0))

    root.mainloop()
