"""EN: MCP server (stdio) — the agent-facing surface of CodeAtlas.

ZH: MCP server（stdio 传输）—— CodeAtlas 面向 AI agent 的入口。

EN: Transport is stdio only. The JSON-RPC stream owns stdout exclusively:
    * never print() to stdout here; logs go to stderr,
    * never import rich consoles from cli.py into the tool path.
  Concurrency: the MCP SDK runs sync tools in a worker pool, and sqlite3
  connections default to check_same_thread=True — so every tool opens its
  own Store via codeatlas.service (per-call stores; WAL already on).
ZH: 传输仅 stdio。JSON-RPC 流独占 stdout：
    * 本模块绝不向 stdout print()；日志一律走 stderr，
    * tool 路径上不从 cli.py 导入 rich Console。
  并发：MCP SDK 的同步 tool 在工作线程池执行，sqlite3 连接默认
  check_same_thread=True —— 因此每个 tool 经 codeatlas.service 自建
  Store（按调用建连接；已开 WAL）。

EN: Requires the `mcp` extra: pip install "codeatlas-memory[mcp]".
ZH: 需要 mcp extra：pip install "codeatlas-memory[mcp]"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import service

# EN: 50KB cap for whole-file tool outputs — keeps agent contexts small and
# matches the project's own token-budget philosophy.
# ZH: 整文件类输出的 50KB 上限 —— 控制 agent 上下文体积，与项目自身的
# token 预算理念一致。
OUTPUT_BYTE_CAP = 50_000

# EN: the tool surface — asserted by tests and documented in the README.
# ZH: 工具面 —— 由测试断言、README 记录。
TOOLS = [
    "scan_project", "update_index",
    "overview", "module_detail",
    "search_symbols", "symbol_history",
    "plan_context",
    "context_load", "context_status", "context_evict",
    "doctor",
]


def _log(msg: str) -> None:
    """stderr-only logging (stdout belongs to the JSON-RPC stream)."""
    print(msg, file=sys.stderr, flush=True)


def _root(raw: str | None) -> Path:
    """Resolve + validate the project root (arg > CODEATLAS_ROOT env > CWD)."""
    return service.resolve_root(raw)


def _no_index() -> str:
    return (
        "No index found. Run codeatlas scan (or the scan_project tool) first. "
        "/ 未找到索引，请先运行 scan（或 scan_project 工具）。"
    )


def _cap(text: str, hint: str) -> str:
    """Cap oversized output with a truncation note (bytes, UTF-8)."""
    data = text.encode("utf-8")
    if len(data) <= OUTPUT_BYTE_CAP:
        return text
    cut = data[:OUTPUT_BYTE_CAP].decode("utf-8", errors="ignore")
    return cut + f"\n\n> [truncated at {OUTPUT_BYTE_CAP} bytes — {hint}]"


def build_server():
    """Construct the MCPServer with all tools registered.

    EN: imported lazily so the rest of the package never needs the mcp SDK.
    ZH: 延迟导入，包的其余部分不依赖 mcp SDK。
    """
    try:
        # EN: mcp 2.x renamed FastMCP -> MCPServer (migration guide v2).
        # ZH: mcp 2.x 将 FastMCP 改名为 MCPServer（见 v2 迁移指南）。
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:  # pragma: no cover - exercised via main()
        raise RuntimeError(
            'The mcp SDK is required: pip install "codeatlas-memory[mcp]" '
            "/ 需要 mcp SDK：pip install \"codeatlas-memory[mcp]\""
        ) from exc

    mcp = MCPServer(
        name="codeatlas",
        instructions=(
            "CodeAtlas gives you a persistent, incrementally-updated memory of "
            "the codebase. Start with overview(), search symbols instead of "
            "grepping, load exactly what you need with context_load (token "
            "budgeted), and finish edits with update_index()."
        ),
    )

    # ------------------------------------------------------------- scan/update

    @mcp.tool()
    def scan_project(root: str | None = None) -> str:
        """Build the code index for a repository (bootstrap).

        Parses every source file and writes CODEATLAS.md plus .codeatlas/.
        Use this once before other tools when no index exists. Large repos
        can take a while — for them prefer running `codeatlas scan .` in the
        shell instead.
        """
        try:
            r = _root(root)
            result = service.scan_project(r, "en")
            return (
                f"Scanned {result.files_scanned} file(s), "
                f"{result.symbols_found} symbol(s). CODEATLAS.md written."
            )
        except FileNotFoundError as e:
            return str(e)

    @mcp.tool()
    def update_index(root: str | None = None) -> str:
        """Incrementally re-index changed files and record a history entry.

        Call after edits are finished. Only changed files are re-parsed;
        symbol changes (renames, signature edits, body diffs) land in
        .codeatlas/history/.
        """
        try:
            r = _root(root)
            outcome = service.update_project(r, "en")
            res = outcome.result
            note = " (no index yet — full scan ran instead)" if outcome.fell_back else ""
            return (
                f"Updated: {res.files_parsed} file(s) re-parsed, "
                f"{res.files_skipped} skipped, {len(res.changes)} symbol change(s).{note}"
            )
        except FileNotFoundError as e:
            return str(e)

    # ------------------------------------------------------------- read paths

    @mcp.tool()
    def overview(root: str | None = None) -> str:
        """Read CODEATLAS.md — the architecture overview of the repository.

        Returns the generated overview: directory tree, module dependencies,
        class inheritance, call graph and a per-file index table. Best first
        call when starting a task in this repo.
        """
        try:
            r = _root(root)
        except FileNotFoundError as e:
            return str(e)
        path = r / "CODEATLAS.md"
        if not path.is_file():
            return _no_index()
        return _cap(
            path.read_text(encoding="utf-8"),
            "use module_detail or search_symbols for targeted reading",
        )

    @mcp.tool()
    def module_detail(module: str, root: str | None = None) -> str:
        """Read the detail shard of one top-level module (symbols, signatures).

        `module` is a top-level directory name (e.g. 'src', 'tests'), or
        'root' for root-level files. Cheaper than overview for targeted work.
        """
        try:
            r = _root(root)
        except FileNotFoundError as e:
            return str(e)
        detail_dir = r / ".codeatlas" / "detail"
        if not detail_dir.is_dir():
            return _no_index()
        target = _match_detail_file(detail_dir, module)
        if target is None:
            available = sorted(p.name for p in detail_dir.glob("*.md"))
            return f"No detail shard for module '{module}'. Available: {', '.join(available)}"
        return _cap(target.read_text(encoding="utf-8"), "use search_symbols for specific symbols")

    # ------------------------------------------------------------- search/history

    @mcp.tool()
    def search_symbols(query: str, limit: int = 20, root: str | None = None) -> str:
        """Full-text symbol search (FTS5 trigram; Chinese works).

        Returns JSON rows: file, line, qualified_name, signature, description.
        Prefer this over grepping — results are symbol-level and ranked.
        """
        try:
            r = _root(root)
            rows = service.search_symbols(r, query, limit)
        except FileNotFoundError as e:
            return str(e)
        if not rows:
            return f"No matches for '{query}'."
        return json.dumps(rows, ensure_ascii=False, indent=1)

    @mcp.tool()
    def symbol_history(symbol: str, max_depth: int = 5, root: str | None = None) -> str:
        """A symbol's evolution chain: changes per update, renames followed.

        Check before refactoring existing code. Renames are linked
        automatically (up to max_depth hops).
        """
        try:
            r = _root(root)
            return service.format_history(r, symbol, max_depth)
        except FileNotFoundError as e:
            return str(e)

    @mcp.tool()
    def plan_context(query: str, root: str | None = None) -> str:
        """Retrieve bounded, deterministic evidence for planning a task.

        Returns JSON with ranked symbols, call-graph neighbours, conventions,
        suggested pages, and impact scope. No source dumps and no LLM calls.
        """
        try:
            r = _root(root)
            payload = service.plan_context(r, query)
        except FileNotFoundError as e:
            return str(e)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    # ------------------------------------------------------------- context VM

    @mcp.tool()
    def context_load(
        symbol: str,
        anchor: int | None = None,
        granularity: str | None = None,
        pin: bool = False,
        source: bool = False,
        root: str | None = None,
    ) -> str:
        """Load one symbol/file page into the token-budgeted working set.

        Returns the page as markdown (signature, callers/callees, related
        files, optional source excerpt). Pages evicted by the budget are
        reported. Ambiguous bare names return the candidate list.
        """
        if granularity not in (None, "function", "file"):
            return "granularity must be 'function' or 'file'"
        try:
            r = _root(root)
            try:
                outcome = service.load_context_page(
                    r, symbol, granularity, anchor=anchor, pin=pin, with_source=source,
                )
            except service.AmbiguousSymbol as amb:
                return json.dumps(
                    {"error": "ambiguous", "candidates": amb.candidates}, ensure_ascii=False
                )
        except FileNotFoundError as e:
            return str(e)
        if outcome.page is None:
            return f"Symbol or file not found: {symbol}"
        notes = []
        for page_id in outcome.evicted:
            notes.append(f"evicted: {page_id}")
        if outcome.unsatisfied > 0:
            notes.append(
                f"warning: {outcome.unsatisfied} tokens could not be freed — "
                "raise the budget via context_status guidance"
            )
        notes.append(f"tokens: {outcome.tokens}")
        return outcome.rendered + "\n" + "\n".join(f"({n})" for n in notes)

    @mcp.tool()
    def context_status(root: str | None = None) -> str:
        """Show the working set: resident pages, tokens, staleness, budget bar."""
        try:
            r = _root(root)
            return service.format_status(r)
        except FileNotFoundError as e:
            return str(e)

    @mcp.tool()
    def context_evict(
        page_id: str | None = None,
        all: bool = False,
        force: bool = False,
        root: str | None = None,
    ) -> str:
        """Evict pages from the working set (all=true keeps pinned unless force).

        One page by id, or all=true for every unpinned page. Pinned pages
        need force=true.
        """
        try:
            r = _root(root)
            return service.evict_pages(r, page_id, all_pages=all, force=force)
        except FileNotFoundError as e:
            return str(e)
        except KeyError as e:
            return str(e.args[0])
        except PermissionError as e:
            return str(e.args[0])
        except ValueError as e:
            return str(e.args[0])

    # ------------------------------------------------------------- health

    @mcp.tool()
    def doctor(root: str | None = None) -> str:
        """Run consistency invariants over the index (call at session end).

        Returns the list of violations, or 'All consistency checks passed.'
        when clean.
        """
        try:
            r = _root(root)
            problems = service.doctor_problems(r)
        except FileNotFoundError as e:
            return str(e)
        if problems:
            return "\n".join(f"VIOLATION: {p}" for p in problems)
        return "All consistency checks passed. / 一致性检查全部通过。"

    return mcp


def _match_detail_file(detail_dir: Path, module: str) -> Path | None:
    """Find `.codeatlas/detail/<module>-<hash>.md` for a module name.

    EN: filenames carry an md5 suffix (markdown._detail_filename); match on
    the prefix before the last '-' and resolve ambiguity by exact prefix.
    ZH: detail 文件名带 md5 后缀（markdown._detail_filename）；按最后一个
    '-' 之前的前缀匹配。
    """
    candidates = [p for p in detail_dir.glob(f"{module}-*.md")]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        return None
    # EN: several hashes with the same prefix — pick deterministically.
    # ZH: 同前缀多个哈希 —— 确定性选取。
    return sorted(candidates)[0]


def main() -> None:
    """Console-script entry point (codeatlas-mcp)."""
    try:
        server = build_server()
    except RuntimeError as e:
        _log(str(e))
        raise SystemExit(2) from e
    server.run("stdio")


if __name__ == "__main__":
    main()
