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
from .changelog import write_codeatlas_gitignore, write_history_doc
from .indexer import run_scan, run_update
from .markdown import render_detail_files, render_overview
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


@app.command()
def serve() -> None:
    """(Placeholder) LSP server — planned for Phase 3."""
    console.print("[yellow]LSP server is planned for Phase 3. / LSP 服务器计划于第三阶段实现。[/yellow]")
    raise typer.Exit(0)


@app.command()
def mcp() -> None:
    """(Placeholder) MCP server — planned for Phase 3."""
    console.print("[yellow]MCP server is planned for Phase 3. / MCP 服务器计划于第三阶段实现。[/yellow]")
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
