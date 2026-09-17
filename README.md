# CodeAtlas

> Persistent Code Index & Architecture Memory for AI-Assisted Development
>
> 为 AI 辅助开发打造的持久代码索引与架构记忆

**This project is not affiliated with any other project named CodeAtlas.**

- [English](README.md) | [简体中文](README.zh-CN.md)

---

## Why / 为什么

AI coding tools (Codex, Cursor, …) have a limited context window. On large
codebases they re-read files on every task, waste tokens, and lose track of
what previous sessions changed.

CodeAtlas gives your AI a **persistent, incrementally-updated memory** of the
project:

- a layered Markdown index (`CODEATLAS.md` overview + per-module detail shards),
- Mermaid diagrams (directory tree, module dependencies, class inheritance,
  call graph),
- a symbol-level change history (old → new, per update, with rollback context),
- keyword search over symbols (Chinese and English),
- an LLM context **virtual memory**: `context load` pages a symbol or file
  into a token-budgeted working set with LRU eviction and neighbour prefetch.

AI 编程工具（Codex、Cursor 等）的上下文窗口有限。面对大型代码库，它们每次
任务都要重读文件、浪费 token，还会忘记上次会话改过什么。

CodeAtlas 为你的 AI 提供**持久、增量更新的项目记忆**：

- 分层 Markdown 索引（`CODEATLAS.md` 总览 + 按模块拆分的明细）；
- Mermaid 图（目录树、模块依赖、类继承、调用图）；
- 符号级变更历史（old → new，按次记录，可支撑回滚）；
- 符号关键字搜索（中英文均可）；
- LLM 上下文**虚拟内存**：`context load` 把符号或文件按页加载进带 token
  预算的工作集，支持 LRU 置换与邻居预取；
- **MCP server**：一行配置接入 Cursor / Claude Code 等 AI 工具，agent 直接
  调用上述全部能力（见下方 [MCP server](#mcp-server-mcp-服务器)）。

## Install / 安装

Requires Python 3.11+. First run downloads dependencies (needs network once).

需要 Python 3.11+。首次运行需联网安装依赖。

```bash
uv sync                       # or: pip install -e .
uv run codeatlas --help
```

## Quick start / 快速开始

```bash
# 1. Full scan: CODEATLAS.md + .codeatlas/{detail,state.db,history}
#    全量扫描：生成 CODEATLAS.md 与 .codeatlas/ 内部状态
codeatlas scan .

# 2. After AI edits your code — incremental: only changed files re-parsed
#    AI 改完代码后 —— 增量更新：只重新解析有变化的文件
codeatlas update .

# 3. Search symbols (FTS5 trigram; Chinese works)
#    搜索符号（FTS5 trigram，支持中文）
codeatlas query "打印消息"
codeatlas query order_total

# 4. A symbol's evolution chain (renames followed automatically)
#    查看符号演变链（自动跟进重命名）
codeatlas history order_total

# 5. Load one symbol into the context working set (virtual memory)
#    把一个符号加载进上下文工作集（虚拟内存）
codeatlas context load order_total
codeatlas context status

# Chinese output everywhere / 全中文输出
codeatlas scan . --lang zh
codeatlas update . --lang zh
```

## What gets written / 产物说明

```
CODEATLAS.md                 # overview: diagrams + one-line-per-file table
                             # 总览：架构图 + 每文件一行索引
.codeatlas/
  state.db                   # SQLite state (regenerable / 可再生，不入库)
  detail/<module>.md         # full symbol detail per top-level dir
                             # 按顶层目录拆分的符号级明细（可再生，不入库）
  history/YYYY-MM-DD_HHMM.md # per-update change record (committed / 按设计入库)
```

`.codeatlas/.gitignore` is generated automatically: `state.db` and `detail/`
are derived artifacts, `history/` is the durable record and **is** committed.

`.codeatlas/.gitignore` 自动生成：`state.db` 与 `detail/` 是可再生派生物，
`history/` 是持久记录，**应该**提交到 git。

## AI usage conventions / AI 使用约定

Put this in your `AGENTS.md` / `.cursorrules`:

将以下内容加入你的 `AGENTS.md` / `.cursorrules`：

```markdown
- Before exploring this repo, read CODEATLAS.md (overview) first.
- Read .codeatlas/detail/<module>.md only for the module you need.
- After finishing changes, run `codeatlas update .` so history stays accurate.
- Use `codeatlas query <keyword>` instead of grep when looking for symbols.
- Check `codeatlas history <symbol>` before refactoring existing code.
```

## MCP server / MCP 服务器

Access all CodeAtlas capabilities from AI agents via the Model Context
Protocol — no shell calls, no AGENTS.md conventions needed.

通过 MCP（Model Context Protocol）让 AI agent 直接调用 CodeAtlas 的全部能力
—— 无需 shell 调用，无需在 `AGENTS.md` 里写约定。

Install with the MCP extra, then register the server:

安装 MCP extra 后注册 server（二选一，推荐 `uvx` 方式，无需全局安装）：

```bash
pip install "codeatlas-memory[mcp]"          # or: uv sync --extra mcp
```

**Cursor** — `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "codeatlas": {
      "command": "uvx",
      "args": ["--from", "codeatlas-memory[mcp]", "codeatlas-mcp"],
      "env": { "CODEATLAS_ROOT": "/absolute/path/to/your/project" }
    }
  }
}
```

**Claude Code**:

```bash
claude mcp add codeatlas -e CODEATLAS_ROOT=/absolute/path/to/project -- uvx --from "codeatlas-memory[mcp]" codeatlas-mcp
```

`CODEATLAS_ROOT` pins the workspace when the client starts the server from an
unknown CWD (fall-back order: tool `root` argument > env var > CWD).

当客户端在未知 CWD 启动 server 时，用 `CODEATLAS_ROOT` 固定项目根
（解析顺序：tool 的 `root` 参数 > 环境变量 > CWD）。

Available tools (10) / 可用工具（10 个）：

| Tool | Purpose / 用途 |
|---|---|
| `overview` | Read `CODEATLAS.md` architecture overview / 读取架构总览 |
| `module_detail` | One module's symbol shard / 读取单模块符号明细 |
| `search_symbols` | FTS search incl. Chinese / 符号搜索（支持中文） |
| `symbol_history` | Rename-following evolution chain / 重命名跟随的演变链 |
| `context_load` | Load one page into the token-budgeted working set / 按预算加载一页 |
| `context_status` | Working-set status + budget bar / 工作集状态与预算 |
| `context_evict` | Evict/pin pages / 淘汰或钉住页面 |
| `scan_project` | Build the index (bootstrap) / 建索引（引导；大仓建议用 CLI） |
| `update_index` | Incremental re-index after edits / 改完增量更新 |
| `doctor` | Consistency invariants / 一致性体检 |

Known limitations / 已知限制：`scan_project` / `update_index` on large repos
can exceed client timeouts — prefer the CLI there; concurrent CLI + MCP
working-set writes remain last-write-wins until the locking phase.
大仓库上 `scan_project` / `update_index` 可能超出客户端超时 —— 建议改用
CLI；CLI 与 MCP 并发写工作集仍为最后写入胜出（加锁在后续阶段）。

Smoke test the server with the official inspector / 用官方 inspector 冒烟：

```bash
npx @modelcontextprotocol/inspector uvx --from "codeatlas-memory[mcp]" codeatlas-mcp
```

## Known limitations / 已知限制

- **Languages**: Python / JavaScript / TypeScript(+TSX) only for now.
  目前仅支持 Python / JavaScript / TypeScript(+TSX)。
- **Summaries are rule-based**: docstring first line, or a bilingual template;
  no LLM is involved in the MVP. 摘要是规则生成的（docstring 首行或模板），
  MVP 不含 LLM。
- **Import edges are heuristic**: filename-based resolution; dynamic imports,
  aliases and re-exports may be missed. 导入边是启发式解析（按文件名），
  动态导入、别名等可能遗漏。
- **Rename detection is heuristic**: same-file add+remove with identical
  signature shape. 重命名检测是启发式（同文件增删对、签名形状一致）。
- **Call graph is approximate**: function-level call edges are resolved
  heuristically; decorator calls, dynamic dispatch and higher-order callbacks
  may be missing or mis-attributed. Dependency diagrams are file-level.
  函数级调用图为近似解析：装饰器调用、动态分派、高阶回调可能缺失或归因
  近似；依赖图为文件级。
- **Working-set writes are last-write-wins**: two terminals writing the
  context working set concurrently do not lock (locking arrives with the
  Phase 3 MCP server). 两个终端并发写上下文工作集不加密锁（最后写入胜出，
  Phase 3 MCP 服务器将加锁）。
- **Windows console (GBK)**: files are always UTF-8; interactive table output
  may replace unprintable chars. Windows 控制台（GBK）：文件始终 UTF-8，
  交互式表格输出可能替换不可打印字符。

## Roadmap / 路线图

- **Phase 3 (done, stdio) / 已交付（stdio）**: MCP server for agent
  integration; LSP next / MCP server 已上线（stdio），LSP 随后
- **Phase 4**: semantic search (local embeddings) / 语义搜索（本地向量）
- **Later**: tree-sitter expansion to Go/Rust/Java; GitHub Actions integration
  / 扩展语言与 CI 集成

## Development / 开发

```bash
uv sync
uv run pytest            # 54 tests
```

License: MIT — see [LICENSE](LICENSE).
