# 半结构化配置 ETL 与 Web 交互式编辑系统

[English](#english) · 中文文档见下文

> **Purpose (for reviewers):** Import **multi-source configuration directories** into **SQLite**, edit records in a **browser UI** with transactional write APIs, pre-render numeric attributes as map layers, and export back to **structured text**. Domain-agnostic ETL + interactive editing pipeline.

```
  content dirs ──► build_db ──► SQLite ──► HTTP API + viewer ──► export zip
                      │              │              │
                      └── validation   └── 19 writes  └── structured text
                          error/warn       atomic txn      + edit log
```

## English

**config-etl-editor** is a Python stack for semi-structured domain configuration:

1. **build_db** — parse DSL-like text files from base + overlay directories into SQLite; graded **error/warning** validation
2. **serve** — static viewer + **19 write APIs**; edits run in **atomic transactions** with revision tracking
3. **layers** — pre-render **27** numeric attribute classes to PNG map tiles
4. **export** — write structured text back in source layout for diff-friendly output

**Verified locally:** **40+** pytest cases; portable Windows bundle via Go launcher (optional).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python run.py --help                                    # CLI build
python -m pytest tests/ -q
python interactive_map/serve.py --database save/map_editor.sqlite
# open http://127.0.0.1:8765/
```

Requires two content roots (base + optional overlay). Game/mod assets stay local — not shipped in repo.

---

## 项目简介

面向 **半结构化文本 ETL · SQLite 建模 · Web 交互编辑 · 批量导出** 的配置流水线：多源目录导入 → 校验建库 → 浏览器可视化编辑 → 结构化文本 zip 导出。

## 项目亮点

- **四段流水线**：`多源目录 → SQLite → 浏览器编辑 → 文本导出`；建库 **error/warning** 分级，异常记录拦截与规则修正
- **事务化编辑**：**19** 个写 API、8 种原子操作，`atomic_edit` 失败整批回滚，`revision` 版本追踪
- **图层预渲染**：**27** 类数值属性（11 类资源上限 + 16 类耕地作物）预计算为 PNG
- **可测试**：**40+** pytest；含 `collect_origin_data` 解析子模块与 `map_db` / `interactive_map` / `runtime` 分层
- **便携部署**：可选 Go 启动器 + Windows 便携包脚本 `build_windows_portable.sh`

## 仓库结构

| 目录 | 职责 |
|------|------|
| `run.py` | CLI 建库入口 |
| `map_db/` | DSL 解析 → SQLite schema |
| `collect_origin_data/` | 共享内容解析库（随仓库 vendored） |
| `interactive_map/` | HTTP API、viewer、图层、导出 |
| `runtime/` | 会话加载与服务状态 |
| `bootstrap/` | 建库任务编排 |
| `tests/` | pytest |
| `launcher_go/` | 便携 Windows 启动器 |

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 从 base + overlay 目录构建 SQLite（路径按本机修改）
python run.py /path/to/overlay -o save/map_editor.sqlite

# 启动 Web 编辑器
python interactive_map/serve.py --database save/map_editor.sqlite
```

浏览器打开 `http://127.0.0.1:8765/`，在启动页加载已有库或触发后台建库。

## 技术栈

Python 3.10+ · SQLite · NumPy / Pillow · stdlib HTTP server · pytest · Go（便携包）

## 详细文档

阶段交付物与校验规则见 [`README`](README)（设计长文档，无 `.md` 后缀）。

## License

MIT — see [LICENSE](LICENSE).

## 相关仓库

- [steam-workshop-etl](https://github.com/Joe-Villa/steam-workshop-etl) — Web 采集与统计分析流水线
- [wizard-rule-codegen](https://github.com/Joe-Villa/wizard-rule-codegen) — 向导式规则引擎与多语言代码生成
