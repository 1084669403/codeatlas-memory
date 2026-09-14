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
- Mermaid diagrams (directory tree, module dependencies, class inheritance),
- a symbol-level change history (old → new, per update, with rollback context),
- keyword search over symbols (Chinese and English).

AI 编程工具（Codex、Cursor 等）的上下文窗口有限。面对大型代码库，它们每次
任务都要重读文件、浪费 token，还会忘记上次会话改过什么。

CodeAtlas 为你的 AI 提供**持久、增量更新的项目记忆**：

- 分层 Markdown 索引（`CODEATLAS.md` 总览 + 按模块拆分的明细）；
- Mermaid 图（目录树、模块依赖、类继承）；
- 符号级变更历史（old → new，按次记录，可支撑回滚）；
- 符号关键字搜索（中英文均可）。

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
- **Call graph is not built yet** (planned Phase 1.5); dependency diagrams are
  file-level. 尚未构建函数级调用图（Phase 1.5 计划）；依赖图为文件级。
- **Windows console (GBK)**: files are always UTF-8; interactive table output
  may replace unprintable chars. Windows 控制台（GBK）：文件始终 UTF-8，
  交互式表格输出可能替换不可打印字符。

## Roadmap / 路线图

- **Phase 1.5**: function-level call graphs / 函数级调用图
- **Phase 3**: MCP server (AI tool integration), then LSP (IDE integration);
  on-demand detail API; `--max-tokens` budget tuning / MCP 服务器优先，LSP 随后
- **Phase 4**: semantic search (local embeddings) / 语义搜索（本地向量）
- **Later**: tree-sitter expansion to Go/Rust/Java; GitHub Actions integration
  / 扩展语言与 CI 集成

## Development / 开发

```bash
uv sync
uv run pytest            # 54 tests
```

License: MIT — see [LICENSE](LICENSE).
