# CodeAtlas

> 为 AI 辅助开发打造的持久代码索引与架构记忆
>
> Persistent Code Index & Architecture Memory for AI-Assisted Development

**本项目与其它同名 CodeAtlas 项目无关。**

- [简体中文](README.zh-CN.md) | [English](README.md)

---

## 为什么需要 / Why

AI 编程工具（Codex、Cursor 等）的上下文窗口有限。面对大型代码库，它们每次
任务都要重读文件、浪费 token，还会忘记上次会话改过什么。

CodeAtlas 为你的 AI 提供**持久、增量更新的项目记忆**：

- 分层 Markdown 索引（`CODEATLAS.md` 总览 + 按模块拆分的明细）；
- Mermaid 图（目录树、模块依赖、类继承、调用图），人与 AI 都能看懂；
- 符号级变更历史（old → new，按次记录，可支撑回滚）；
- 符号关键字搜索（中英文均可）；
- LLM 上下文**虚拟内存**：`context load` 把符号或文件按页加载进带 token
  预算的工作集，支持 LRU 置换与邻居预取；
- **MCP 服务器**：一行配置接入 Cursor / Claude Code 等 AI 工具，agent 直接
  调用上述全部能力（见下方 [MCP 服务器](#mcp-服务器--mcp-server)）。

AI coding tools (Codex, Cursor, …) have a limited context window. On large
codebases they re-read files on every task, waste tokens, and lose track of
what previous sessions changed.

CodeAtlas gives your AI a **persistent, incrementally-updated memory** of the
project: a layered Markdown index, Mermaid architecture diagrams, a
symbol-level change history with rollback context, and keyword search over
symbols (Chinese and English).

## 安装 / Install

需要 Python 3.11+。首次运行需联网安装依赖。

Requires Python 3.11+. First run downloads dependencies (needs network once).

```bash
uv sync                       # 或: pip install -e .
uv run codeatlas --help
```

## 快速开始 / Quick start

```bash
# 1. 全量扫描：生成 CODEATLAS.md 与 .codeatlas/ 内部状态
codeatlas scan .

# 2. AI 改完代码后 —— 增量更新：只重新解析有变化的文件，并生成变更记录
codeatlas update .

# 3. 搜索符号（FTS5 trigram，支持中文）
codeatlas query "打印消息"
codeatlas query order_total

# 4. 查看符号演变链（自动跟进重命名，最多 5 层）
codeatlas history order_total

# 5. 把一个符号加载进上下文工作集（虚拟内存）
codeatlas context load order_total
codeatlas context status

# 全中文输出
codeatlas scan . --lang zh
codeatlas update . --lang zh
```

## 产物说明 / What gets written

```
CODEATLAS.md                 # 总览：架构图 + 每文件一行索引
.codeatlas/
  state.db                   # SQLite 状态库（可再生，不入库）
  detail/<module>.md         # 按顶层目录拆分的符号级明细（可再生，不入库）
  history/YYYY-MM-DD_HHMM.md # 每次 update 的变更记录（按设计入库）
```

`.codeatlas/.gitignore` 自动生成：`state.db` 与 `detail/` 是可再生派生物，
`history/` 是持久记录，**应该**提交到 git——它是 AI 回滚与审阅的依据。

## AI 使用约定 / AI usage conventions

将以下内容加入你的 `AGENTS.md` / `.cursorrules`：

```markdown
- 浏览本仓库前，先读 CODEATLAS.md（总览）。
- 只按需读取 .codeatlas/detail/<module>.md，不要一次读全部。
- 完成修改后运行 `codeatlas update .`，保证变更历史准确。
- 查找符号时优先用 `codeatlas query <关键词>`，而不是 grep。
- 重构既有代码前，先 `codeatlas history <符号>` 查看演变链。
```

## MCP 服务器 / MCP server

通过 MCP（Model Context Protocol）让 AI agent 直接调用 CodeAtlas 的全部能力
—— 无需 shell 调用，无需在 `AGENTS.md` 里写约定。

安装 MCP extra 后注册 server（推荐 `uvx` 方式，无需全局安装）：

```bash
pip install "codeatlas-memory[mcp]"          # 或: uv sync --extra mcp
```

**Cursor** —— 项目级 `.cursor/mcp.json` 或全局 `~/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "codeatlas": {
      "command": "uvx",
      "args": ["--from", "codeatlas-memory[mcp]", "codeatlas-mcp"],
      "env": { "CODEATLAS_ROOT": "项目根目录的绝对路径" }
    }
  }
}
```

**Claude Code**:

```bash
claude mcp add codeatlas -e CODEATLAS_ROOT=项目根绝对路径 -- uvx --from "codeatlas-memory[mcp]" codeatlas-mcp
```

客户端在未知 CWD 启动 server 时，用 `CODEATLAS_ROOT` 固定项目根
（解析顺序：tool 的 `root` 参数 > 环境变量 > CWD）。

可用工具（10 个）：

| 工具 | 用途 |
|---|---|
| `overview` | 读取 `CODEATLAS.md` 架构总览 |
| `module_detail` | 读取单模块符号明细 |
| `search_symbols` | 符号搜索（FTS，支持中文） |
| `symbol_history` | 重命名跟随的符号演变链 |
| `context_load` | 按预算加载一页进工作集 |
| `context_status` | 工作集状态与预算进度 |
| `context_evict` | 淘汰或钉住页面 |
| `scan_project` | 建索引（引导；大仓库建议用 CLI） |
| `update_index` | 改完增量更新 |
| `doctor` | 一致性体检 |

已知限制：大仓库上 `scan_project` / `update_index` 可能超出客户端超时，
建议改用 CLI；CLI 与 MCP 并发写工作集仍为最后写入胜出（加锁在后续阶段）。

用官方 inspector 冒烟验证：

```bash
npx @modelcontextprotocol/inspector uvx --from "codeatlas-memory[mcp]" codeatlas-mcp
```

English version:

```markdown
- Before exploring this repo, read CODEATLAS.md (overview) first.
- Read .codeatlas/detail/<module>.md only for the module you need.
- After finishing changes, run `codeatlas update .` so history stays accurate.
- Use `codeatlas query <keyword>` instead of grep when looking for symbols.
- Check `codeatlas history <symbol>` before refactoring existing code.
```

## 变更记录长什么样 / What history looks like

每次 `update` 生成 `.codeatlas/history/YYYY-MM-DD_HHMM.md`，按文件分组记录：

```markdown
## `src/service.py`

- **签名变更** `src.service.order_total`
  - old: `def order_total(items: list[int]) -> int`
  - new: `def order_total(items: list[int], discount: float = 0.0) -> float`
- **新增** `src.service.OrderService.refund` — `def refund(self, item: int) -> bool`
```

距离上次记录超过 30 分钟时，文档顶部会出现提示：
"⚠️ 本记录可能未覆盖全部中间状态"——提醒 AI 谨慎回滚。

## 已知限制 / Known limitations

- **语言**：目前仅支持 Python / JavaScript / TypeScript(+TSX)。
- **摘要为规则生成**：取 docstring 首行，或用双语模板补位；MVP 不含 LLM。
- **导入边是启发式**：按文件名解析；动态导入、别名、再导出可能遗漏。
- **重命名检测是启发式**：同文件内"增删对 + 去名签名形状一致"才判定。
- **调用图为近似解析**：函数级调用边按启发式解析；装饰器调用、动态分派、
  高阶回调可能缺失或归因近似；依赖图为文件级。
- **工作集并发写为最后写入胜出**：两个终端并发写上下文工作集不加密锁
  （Phase 3 MCP 服务器将加锁）。
- **Windows 控制台（GBK）**：文件始终 UTF-8；交互式表格可能替换不可打印字符。
- **联网**：仅首次 `uv sync` / `pip install` 需要网络；扫描与查询完全本地。

## 路线图 / Roadmap

- **Phase 3（已交付 stdio）**：MCP 服务器已上线；LSP（IDE 集成）随后
- **Phase 4**：语义搜索（本地向量，sqlite-vec）
- **更远**：tree-sitter 扩展 Go/Rust/Java；GitHub Actions 集成

## 开发 / Development

```bash
uv sync
uv run pytest            # 测试套件（含 MCP server 测试）
```

License: MIT — see [LICENSE](LICENSE).
