"""EN: Typer CLI application — the user-facing surface of CodeAtlas.
ZH: Typer CLI 应用 —— CodeAtlas 的用户入口。

Commands:
    scan    full scan -> CODEATLAS.md + .codeatlas/detail/ + state
    update  incremental update -> only changed files re-parsed + history doc
    query   full-text symbol search (FTS5 trigram, LIKE fallback)
    history symbol evolution chain from the append-only changes table
    serve   (placeholder, Phase 3)
    mcp     (placeholder, Phase 3)
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .callgraph import rebuild_call_edges
from .changelog import write_codeatlas_gitignore, write_history_doc
from .consistency import run_all_checks
from .indexer import run_scan, run_update
from .markdown import render_detail_files, render_overview
from .memory import (
    AmbiguousSymbol,
    PageStatus,
    ensure_budget,
    load_budget,
    load_page,
    render_page_with_store,
    render_working_set,
    save_budget,
    status as ws_status,
)
from .prefetch import prefetch as do_prefetch
from .storage import Store

app = typer.Typer(
    name="codeatlas",
    help="Persistent code index & architecture memory for AI-assisted development.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

LangOpt = typer.Option("en", "--lang", "-l", help="Output language: en or zh.")
TokensOpt = typer.Option(None, "--max-tokens", "-t", help="Token budget for the overview file table.")


def _open_store(root: Path) -> Store:
    """Open (creating if needed) the .codeatlas/state.db for a project root."""
    codeatlas_dir = root / ".codeatlas"
    codeatlas_dir.mkdir(parents=True, exist_ok=True)
    return Store(codeatlas_dir / "state.db")


def _lang_switch_notice(result, lang: str) -> None:
    # EN: run_update signals a language switch via the files_skipped sentinel.
    # ZH: run_update 通过 files_skipped 哨兵值通知语言切换。
    if result.files_skipped == -1:
        result.files_skipped = 0
        if lang == "zh":
            console.print("[yellow]输出语言已变更，已自动全量重扫以保持描述一致。[/yellow]")
        else:
            console.print("[yellow]Output language changed — full re-scan performed for consistency.[/yellow]")


@app.command()
def scan(
    path: Path = typer.Argument(Path("."), help="Project root to scan."),
    lang: str = LangOpt,
    max_tokens: int | None = TokensOpt,
) -> None:
    """Full scan: build CODEATLAS.md, detail shards and the state database."""
    root = path.resolve()
    if not root.is_dir():
        err_console.print(f"[red]Not a directory: {root}[/red]")
        raise typer.Exit(2)
    if lang not in ("en", "zh"):
        err_console.print("[red]--lang must be 'en' or 'zh'[/red]")
        raise typer.Exit(2)

    with console.status(f"[bold green]Scanning {root} ..."):
        store = _open_store(root)
        try:
            result = run_scan(root, store, output_lang=lang)
            codeatlas_dir = root / ".codeatlas"
            render_detail_files(store, codeatlas_dir / "detail", lang)
            render_overview(
                root, store, result, root / "CODEATLAS.md",
                lang=lang, max_tokens=max_tokens,
            )
            write_codeatlas_gitignore(codeatlas_dir)
        finally:
            store.close()

    console.print(
        f"[green]Scanned[/green] {result.files_scanned} file(s), "
        f"{result.symbols_found} symbol(s) -> CODEATLAS.md"
    )
    # EN: full rebuild invalidates the working set — say so explicitly (plan v5).
    # ZH: 全量重建使工作集失效 —— 显式提示（方案 v5）。
    console.print(
        "[yellow]项目已重建，工作集已清空。/ Project rebuilt — working set cleared.[/yellow]"
    )


@app.command()
def update(
    path: Path = typer.Argument(Path("."), help="Project root to update."),
    lang: str = LangOpt,
    max_tokens: int | None = TokensOpt,
) -> None:
    """Incremental update: re-parse changed files only; write a history doc."""
    root = path.resolve()
    db = root / ".codeatlas" / "state.db"
    if not db.is_file():
        # EN: friendlier UX: update without state falls back to scan.
        # ZH: 无状态库时退化为 scan（对用户更友好）。
        if lang == "zh":
            console.print("[yellow]未找到状态库，将执行全量扫描。[/yellow]")
        else:
            console.print("[yellow]No state db found — falling back to full scan.[/yellow]")
        scan(path=path, lang=lang, max_tokens=max_tokens)
        return

    store = _open_store(root)
    try:
        result = run_update(root, store, output_lang=lang)
        _lang_switch_notice(result, lang)
        codeatlas_dir = root / ".codeatlas"
        render_detail_files(store, codeatlas_dir / "detail", lang)
        render_overview(
            root, store, result, root / "CODEATLAS.md",
            lang=lang, max_tokens=max_tokens,
        )
        history_path = write_history_doc(
            codeatlas_dir / "history", store, result.changes, result.timestamp,
            lang=lang, files_parsed=result.files_parsed, files_scanned=result.files_scanned,
        )
    finally:
        store.close()

    console.print(
        f"[green]Updated[/green] {result.files_parsed} file(s) re-parsed, "
        f"{result.files_skipped} skipped, {len(result.changes)} symbol change(s); "
        f"history -> {history_path.name}"
    )


@app.command()
def query(
    text: str = typer.Argument(..., help="Search text (symbol name / signature / description)."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results."),
) -> None:
    """Search symbols (FTS5 trigram when available; LIKE fallback otherwise)."""
    root = path.resolve()
    db = root / ".codeatlas" / "state.db"
    if not db.is_file():
        err_console.print(
            "[red]No index found. Run `codeatlas scan .` first. "
            "/ 未找到索引，请先运行 `codeatlas scan .`[/red]"
        )
        raise typer.Exit(2)

    store = Store(db)
    try:
        rows = _search(store, text, limit)
    finally:
        store.close()

    if not rows:
        console.print(f"[yellow]No matches for '{text}'.[/yellow]")
        return

    table = Table(title=f"query: {text} ({len(rows)} hits)")
    table.add_column("Location", style="cyan", no_wrap=True)
    table.add_column("Symbol", style="bold")
    table.add_column("Signature", overflow="fold")
    table.add_column("Description", overflow="fold")
    # EN: Text() cells avoid rich markup parsing — signatures contain [x]
    # (e.g. list[int]) that would be parsed as style tags.
    # ZH: 用 Text() 单元格避免 rich 标记解析 —— 签名里的 [x]
    # （如 list[int]）会被误当样式标签。
    from rich.text import Text

    for r in rows:
        table.add_row(
            Text(f"{r[0]}:{r[1]}"),
            Text(r[2]),
            Text(r[3]),
            Text(r[4]),
        )
    console.print(table)


def _search(store: Store, text: str, limit: int) -> list[tuple]:
    """FTS5 + bm25 ranking; <3-char queries and missing FTS fall back to LIKE.

    EN: LIKE fallback keeps a sensible priority order: exact name > prefix >
    description > path. trigram needs >=3 chars, shorter queries must use LIKE.
    ZH: LIKE 回退保持合理优先级：名称精确 > 前缀 > 描述 > 路径。
    trigram 需要 >=3 字符，更短的查询必须走 LIKE。
    """
    if store.fts_enabled and len(text) >= 3:
        sql = (
            "SELECT s.file, s.line, s.qualified_name, s.signature, s.description "
            "FROM symbols_fts f JOIN symbols s ON s.rowid = f.rowid "
            "WHERE symbols_fts MATCH ? ORDER BY bm25(symbols_fts) LIMIT ?"
        )
        try:
            return list(store.conn.execute(sql, (text, limit)))
        except Exception:
            pass  # fall through to LIKE on query syntax errors
    like = f"%{text}%"
    sql = (
        "SELECT file, line, qualified_name, signature, description FROM ("
        "  SELECT *, CASE"
        "    WHEN name = :t THEN 0"
        "    WHEN name LIKE :p THEN 1"
        "    WHEN description LIKE :l THEN 2"
        "    ELSE 3 END AS prio"
        "  FROM symbols"
        "  WHERE qualified_name LIKE :l OR description LIKE :l"
        ") ORDER BY prio, qualified_name LIMIT :lim"
    )
    return list(
        store.conn.execute(sql, {"t": text, "p": f"{text}%", "l": like, "lim": limit})
    )


@app.command()
def history(
    symbol: str = typer.Argument(..., help="Symbol name (bare) or qualified name."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    max_depth: int = typer.Option(5, "--depth", help="Max rename-chain hops."),
) -> None:
    """Show a symbol's evolution chain (renames are followed automatically)."""
    root = path.resolve()
    db = root / ".codeatlas" / "state.db"
    if not db.is_file():
        err_console.print(
            "[red]No index found. Run `codeatlas scan .` first. "
            "/ 未找到索引，请先运行 `codeatlas scan .`[/red]"
        )
        raise typer.Exit(2)

    store = Store(db)
    try:
        _print_history(store, symbol, max_depth)
    finally:
        store.close()


def _print_history(store: Store, symbol: str, max_depth: int) -> None:
    """Resolve bare vs qualified names, follow rename chains, print the chain.

    EN: A bare name may match several qualified symbols — list them all.
    RENAMED records link old qname -> new qname; we follow up to max_depth
    hops to keep the chain connected across renames.
    ZH: 裸名可能匹配多个限定名 —— 全部列出。RENAMED 记录提供
    旧名 -> 新名的链接，最多跟进 max_depth 跳保证跨重命名连续。
    """
    names: list[str]
    if "." in symbol:
        names = [symbol]
    else:
        counts = store.changes_by_symbol_name(symbol)
        if not counts:
            console.print(f"[yellow]No history for '{symbol}'.[/yellow]")
            return
        names = sorted(counts)
        if len(names) > 1:
            console.print(f"[dim]{len(names)} qualified symbols match '{symbol}':[/dim]")

    seen: set[str] = set()
    for name in names:
        console.rule(f"[bold]{name}")
        depth = 0
        current = name
        while current and current not in seen and depth <= max_depth:
            seen.add(current)
            records = store.changes_for_symbol(current)
            if not records:
                break
            for rec in records:
                detail = f" [dim]{rec.detail}[/dim]" if rec.detail else ""
                console.print(
                    f"  [cyan]{rec.ts}[/cyan] [bold]{rec.change_type.value}[/bold] "
                    f"old={rec.old_value!r} new={rec.new_value!r}{detail}"
                )
            # follow rename chain both directions
            renamed_to = next(
                (r.new_value for r in records if r.change_type.value == "renamed"), None
            )
            current = renamed_to
            depth += 1


# ==========================================================================
# EN: context command group — LLM context virtual memory surface.
# ZH: context 命令组 —— LLM 上下文虚拟内存入口。
# ==========================================================================

context_app = typer.Typer(help="LLM context virtual memory: load/status/evict/budget.", no_args_is_help=True)
app.add_typer(context_app, name="context")


def _require_index(path: Path) -> tuple[Path, Store]:
    """Open the store or exit 1 with the standard no-index message (plan v6)."""
    root = path.resolve()
    db = root / ".codeatlas" / "state.db"
    if not db.is_file():
        err_console.print(
            "[red]No index found. Run `codeatlas scan .` first. "
            "/ 未找到索引，请先运行 `codeatlas scan .`[/red]"
        )
        raise typer.Exit(1)
    return root, Store(db)


@context_app.command("load")
def context_load(
    symbol: str = typer.Argument(..., help="Qualified/bare symbol name or file path."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    anchor: int | None = typer.Option(None, "--anchor", help="Anchor line for locality."),
    granularity: str | None = typer.Option(None, "--granularity", help="function | file."),
    pin: bool = typer.Option(False, "--pin", help="Pin the page against eviction."),
    no_prefetch: bool = typer.Option(False, "--no-prefetch", help="Skip neighbour prefetch."),
    source: bool = typer.Option(False, "--source", help="Attach a body excerpt (<=800 tokens)."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of markdown."),
) -> None:
    """Load one page into the working set and print it (pure markdown to stdout)."""
    if granularity not in (None, "function", "file"):
        err_console.print("[red]--granularity must be 'function' or 'file'[/red]")
        raise typer.Exit(2)
    root, store = _require_index(path)
    try:
        try:
            # EN: anchor is written inside load_page AFTER the page resolves —
            # ambiguity/not-found never pollute meta['last_anchor'] (plan v6).
            # ZH: 锚点在 load_page 内部、页面解析成功后才写入 —— 歧义/未找到
            # 不会污染 meta['last_anchor']（方案 v6）。
            page = load_page(
                store, symbol, granularity, anchor_line=anchor, pin=pin, origin="load", with_source=source,
            )
        except AmbiguousSymbol as amb:
            if json_output:
                import json as _json

                print(_json.dumps({"error": "ambiguous", "candidates": amb.candidates}, ensure_ascii=False))
            else:
                err_console.print(f"[yellow]Ambiguous symbol '{symbol}'. Candidates:[/yellow]")
                for cand in amb.candidates:
                    err_console.print(f"  - {cand}")
            raise typer.Exit(2)
        if page is None:
            err_console.print(f"[red]Symbol or file not found: {symbol}[/red]")
            raise typer.Exit(1)

        evicted, unsatisfied = ensure_budget(store)
        if unsatisfied > 0:
            err_console.print(
                f"[yellow]Warning: {unsatisfied} tokens could not be freed — "
                "consider raising the working-set budget (`context budget --working-set N`).[/yellow]"
            )
        for page_id in evicted:
            err_console.print(f"[dim]evicted: {page_id}[/dim]")

        if not no_prefetch:
            do_prefetch(store, page)

        from .memory import page_cost as _page_cost

        tokens = _page_cost(page)
        if json_output:
            import json as _json

            current_hash = store.get_file_hash(page.file)
            print(
                _json.dumps(
                    {
                        "page": {
                            "page_id": page.page_id,
                            "granularity": page.granularity,
                            "file": page.file,
                            "line": page.line,
                            "end_line": page.end_line,
                            "signature": page.signature,
                            "callers": page.callers,
                            "callees": page.callees,
                            "related_files": page.related_files,
                        },
                        "tokens": tokens,
                        "stale": bool(current_hash and current_hash != page.version),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            # EN: pure print — no rich folding/ANSI; piping is lossless (v6).
            # ZH: 纯 print —— 无 rich 折行/ANSI；管道输出无损（v6）。
            print(render_page_with_store(store, page))
    finally:
        store.close()


@context_app.command("status")
def context_status(
    path: Path = typer.Argument(Path("."), help="Project root."),
) -> None:
    """Show the working set: pages, tokens, recency, stale/gone, budget bar."""
    _root, store = _require_index(path)
    try:
        rows: list[PageStatus] = ws_status(store)
        b = load_budget(store)
        table = Table(title="context status / 工作集")
        table.add_column("Page", style="cyan", no_wrap=True)
        table.add_column("Gran", no_wrap=True)
        table.add_column("Tokens", justify="right")
        table.add_column("Last access", no_wrap=True)
        table.add_column("Ver", no_wrap=True)
        table.add_column("State", no_wrap=True)
        table.add_column("Flags", no_wrap=True)
        from rich.text import Text

        total_tokens = 0
        for r in rows:
            total_tokens += r.tokens
            flags = []
            if r.pinned:
                flags.append("pinned")
            if r.origin == "prefetch":
                flags.append("prefetch")
            state_color = {"fresh": "green", "stale": "yellow", "gone": "red"}.get(r.state, "white")
            last = r.last_access_at[:19].replace("T", " ")
            # EN: loaded@N vs current comparison (plan v6); "-" when the page
            # row is gone.
            # ZH: loaded@N vs current 对照（方案 v6）；gone 页显示 "-"。
            if r.loaded_index_version:
                ver_note = f"{r.loaded_index_version}/{r.current_index_version}"
            else:
                ver_note = "-"
            table.add_row(
                Text(r.page_id),
                r.granularity,
                Text(str(r.tokens)),
                Text(last),
                Text(ver_note),
                Text(r.state, style=state_color),
                Text(",".join(flags) if flags else "-"),
            )
        console.print(table)

        # EN: budget progress bar (used/total + page headroom).
        # ZH: 预算进度条（used/total + 页数余量）。
        from rich.progress import Progress, BarColumn, TextColumn

        pct = min(1.0, total_tokens / b.total) if b.total else 0.0
        progress = Progress(
            TextColumn("[bold]budget[/bold]"),
            BarColumn(),
            TextColumn(f"{total_tokens}/{b.total} tokens ({pct:.0%})"),
            TextColumn(
                f"· pages {len(rows)}/{b.max_pages}"
                + ("" if len(rows) <= b.max_pages else " [red](over)[/red]")
            ),
        )
        progress.add_task("budget", total=100, completed=pct * 100)
        console.print(progress)

        if store.evict_count() > 0:
            ratio = store.evict_count() / b.max_pages if b.max_pages else 0
            if ratio > 0.4:
                console.print(
                    f"[yellow]{store.evict_count()} page(s) evicted (>40% of max-pages) — "
                    "consider `context budget --working-set N --max-pages M`[/yellow]"
                )
    finally:
        store.close()


@context_app.command("evict")
def context_evict(
    page_id: str = typer.Argument(None, help="Page to evict (or --all)."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    all_pages: bool = typer.Option(False, "--all", help="Evict every unpinned page."),
    pin: bool = typer.Option(False, "--pin", help="Pin instead of evict."),
    unpin: bool = typer.Option(False, "--unpin", help="Unpin the page."),
    force: bool = typer.Option(False, "--force", help="With --all: evict pinned pages too."),
) -> None:
    """Evict pages from the working set (--all keeps pinned; --force evicts all)."""
    _root, store = _require_index(path)
    try:
        if pin or unpin:
            target = page_id
            entry = store.get_working_set_entry(target)
            if entry is None:
                err_console.print(f"[red]Not in working set: {target}[/red]")
                raise typer.Exit(1)
            entry.pinned = pin and True or (False if unpin else entry.pinned)
            store.upsert_working_set(entry)
            console.print(f"[green]{'pinned' if pin else 'unpinned'}[/green] {target}")
            return
        if all_pages:
            from .memory import evict as _evict

            entries = store.working_set_entries()
            if not force:
                entries = [e for e in entries if not e.pinned]
            total = sum(e.tokens for e in entries)
            evicted, _unsat = _evict(store, total)
            console.print(f"[green]Evicted[/green] {len(evicted)} page(s)")
            return
        if not page_id:
            err_console.print("[red]Provide a page_id or --all[/red]")
            raise typer.Exit(2)
        entry = store.get_working_set_entry(page_id)
        if entry is None:
            err_console.print(f"[red]Not in working set: {page_id}[/red]")
            raise typer.Exit(1)
        if entry.pinned and not force:
            err_console.print("[yellow]Page is pinned — use --force to evict.[/yellow]")
            raise typer.Exit(1)
        store.delete_working_set_entry(page_id)
        console.print(f"[green]Evicted[/green] {page_id}")
    finally:
        store.close()


@context_app.command("budget")
def context_budget(
    path: Path = typer.Argument(Path("."), help="Project root."),
    total: int | None = typer.Option(None, "--total", help="Merged-output token cap."),
    working_set: int | None = typer.Option(None, "--working-set", help="Resident eviction budget."),
    max_pages: int | None = typer.Option(None, "--max-pages", help="Max resident pages."),
) -> None:
    """Show or adjust the token budget (no args = show current)."""
    _root, store = _require_index(path)
    try:
        b = load_budget(store)
        if total is None and working_set is None and max_pages is None:
            console.print(f"total: {b.total} tokens (merged output cap / 合并输出上限)")
            console.print(f"working-set: {b.working_set} tokens (eviction budget / 淘汰预算)")
            console.print(f"max-pages: {b.max_pages}")
            return
        if total is not None:
            b.total = total
        if working_set is not None:
            b.working_set = working_set
        if max_pages is not None:
            b.max_pages = max_pages
        save_budget(store, b)
        console.print(f"[green]Budget saved:[/green] total={b.total} working-set={b.working_set} max-pages={b.max_pages}")
    finally:
        store.close()


@context_app.command("ws")
def context_ws(
    path: Path = typer.Argument(Path("."), help="Project root."),
    lang: str = "en",
) -> None:
    """Print the merged working set (render_working_set) as markdown."""
    _root, store = _require_index(path)
    try:
        print(render_working_set(store, lang))
    finally:
        store.close()


@app.command()
def doctor(
    path: Path = typer.Argument(Path("."), help="Project root."),
) -> None:
    """Run consistency invariants; exit 1 on violations."""
    root, store = _require_index(path)
    try:
        history_dir = root / ".codeatlas" / "history"
        problems = run_all_checks(store, root, history_dir if history_dir.is_dir() else None)
        # EN: budget/callgraph advice (plan: 淘汰率建议 + 解析率报告).
        # ZH: 预算/调用图建议（方案：淘汰率建议 + 解析率报告）。
        b = load_budget(store)
        entries = store.working_set_entries()
        used = sum(e.tokens for e in entries)
        if used > b.working_set:
            problems.append(
                f"working set {used} tokens exceeds budget {b.working_set} — run `context evict --all`"
            )
        rate_raw = store.get_meta("call_resolution_rate")
        if rate_raw:
            console.print(f"[dim]call resolution rate: {float(rate_raw):.0%}[/dim]")
    finally:
        store.close()

    if problems:
        for p in problems:
            err_console.print(f"[red]✗[/red] {p}")
        raise typer.Exit(1)
    console.print("[green]All consistency checks passed. / 一致性检查全部通过。[/green]")


@app.command()
def serve(
    lsp: bool = typer.Option(False, "--lsp", help="Run in LSP mode (placeholder shape)."),
) -> None:
    """(Placeholder) LSP/MCP server — planned for Phase 3."""
    if lsp:
        console.print(
            "[yellow]LSP server is planned for Phase 3. / LSP 服务器计划于第三阶段实现。[/yellow]"
        )
    else:
        console.print(
            "[yellow]Server mode is planned for Phase 3. / 服务器模式计划于第三阶段实现。[/yellow]"
        )
    console.print(
        "[dim]Planned MCP tools: codeatlas_load_page / get_working_set / evict_page / prefetch[/dim]"
    )
    raise typer.Exit(0)


@app.command()
def mcp() -> None:
    """(Placeholder) MCP server — planned for Phase 3."""
    console.print("[yellow]MCP server is planned for Phase 3. / MCP 服务器计划于第三阶段实现。[/yellow]")
    console.print(
        "[dim]Planned MCP tools: codeatlas_load_page / get_working_set / evict_page / prefetch[/dim]"
    )
    raise typer.Exit(0)


@app.command()
def version() -> None:
    """Print the CodeAtlas version."""
    console.print(f"codeatlas {__version__}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
