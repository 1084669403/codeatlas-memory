"""EN: Typer CLI application — the user-facing surface of CodeAtlas.
ZH: Typer CLI 应用 —— CodeAtlas 的用户入口。

Commands:
    scan    full scan -> CODEATLAS.md + .codeatlas/detail/ + state
    update  incremental update -> only changed files re-parsed + history doc
    query   full-text symbol search (FTS5 trigram, LIKE fallback)
    history symbol evolution chain from the append-only changes table
    context LLM context virtual memory (load/status/evict/budget/ws)
    doctor  consistency invariants
    mcp     MCP server (stdio) for AI agent integration
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from . import service
from .memory import AmbiguousSymbol, load_budget, save_budget
from .plans import (
    PlanError,
    find_plan,
    lint_plans,
    plan_status,
    plan_view,
)
from .plan_workflow import approve_plan, create_plan, diff_plan, reapprove_plan, revise_plan
from .plan_workflow import complete_batch, find_gate_definition, mark_batch_stale, record_gate_result, reopen_batch, start_batch
from .gates import run_gate
from .plan_memory import detect_stale_evidence
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
    # EN: thin wrapper over the shared service layer (kept for tests/callers).
    # ZH: 共享服务层的薄封装（保留给测试与调用方）。
    return service.open_store(root)


def _lang_switch_notice(result, lang: str) -> None:
    # EN: service.update_project zeroes the sentinel; outcome.language_switched
    # is the preferred signal. Kept for direct ScanResult callers.
    # ZH: service.update_project 已将哨兵归零；优先用 outcome.language_switched。
    # 保留给直接使用 ScanResult 的调用方。
    if getattr(result, "files_skipped", 0) == -1:
        result.files_skipped = 0
        if lang == "zh":
            console.print("[yellow]输出语言已变更，已自动全量重扫以保持描述一致。[/yellow]")
        else:
            console.print("[yellow]Output language changed — full re-scan performed for consistency.[/yellow]")


def _print_json(payload: object) -> None:
    """Print deterministic plain JSON; stdout remains safe for piping."""
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _plans_dir(root: Path, plans_dir: Path) -> Path:
    """Resolve the plan directory and prevent paths outside the project root."""
    directory = plans_dir if plans_dir.is_absolute() else root / plans_dir
    resolved = directory.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise PlanError("PLAN_OUTSIDE_ROOT", f"Plans directory is outside project root: {plans_dir}", path=directory.as_posix())
    return resolved


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
        try:
            result = service.scan_project(root, lang, max_tokens)
        finally:
            pass

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

    outcome = service.update_project(root, lang, max_tokens)
    result = outcome.result
    if outcome.language_switched:
        if lang == "zh":
            console.print("[yellow]输出语言已变更，已自动全量重扫以保持描述一致。[/yellow]")
        else:
            console.print("[yellow]Output language changed — full re-scan performed for consistency.[/yellow]")
    history_path = outcome.history_path

    console.print(
        f"[green]Updated[/green] {result.files_parsed} file(s) re-parsed, "
        f"{result.files_skipped} skipped, {len(result.changes)} symbol change(s); "
        f"history -> {history_path.name}"
    )
    affected_plans = (outcome.impact_report or {}).get("affected_plans", [])
    if affected_plans:
        console.print("[bold]Affected open plans[/bold]")
        for plan in affected_plans:
            batches = ", ".join(plan["affected_batches"])
            refs = ", ".join(str(item["ref"]) for item in plan["items"])
            console.print(f"- {plan['plan_id']} [{batches}] -> {refs}")
    for warning in (outcome.impact_report or {}).get("warnings", []):
        err_console.print(f"[yellow]Plan impact {warning['code']}: {warning['message']}[/yellow]")
    plan_state = outcome.plan_state_report or {}
    marked_batches = plan_state.get("marked", [])
    skipped_batches = plan_state.get("skipped", [])
    if marked_batches or skipped_batches:
        console.print("[bold]Plan state updates[/bold]")
        for item in marked_batches:
            console.print(
                f"[yellow]Marked batch {item['batch']} stale for revalidation: "
                f"{item['plan_id']}[/yellow]"
            )
        for item in skipped_batches:
            console.print(
                f"[yellow]Skipped plan state write {item['plan_id']} batch {item['batch']}: "
                f"{item['code']}[/yellow]"
            )
    elif plan_state.get("allow_update_plan_state") is False:
        console.print("[yellow]Plan-state writes are disabled; stale evidence is report-only.[/yellow]")


@app.command()
def query(
    text: str = typer.Argument(..., help="Search text (symbol name / signature / description)."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results."),
) -> None:
    """Search symbols (FTS5 trigram when available; LIKE fallback otherwise)."""
    root = path.resolve()
    try:
        rows = service.search_symbols(root, text, limit)
    except FileNotFoundError:
        err_console.print(
            f"[red]{service.NO_INDEX_MSG}[/red]"
        )
        raise typer.Exit(2)

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
            Text(f"{r['file']}:{r['line']}"),
            Text(r["qualified_name"]),
            Text(r["signature"]),
            Text(r["description"]),
        )
    console.print(table)


def _search(store: Store, text: str, limit: int) -> list[tuple]:
    """Deprecated: use service.search_symbols (kept for direct callers)."""
    from .service import _search_row

    # EN: this helper historically took an open Store; recreate the tuples.
    # ZH: 该辅助函数历史上接收已打开的 Store；此处重建元组返回。
    if store.fts_enabled and len(text) >= 3:
        sql = (
            "SELECT s.file, s.line, s.qualified_name, s.signature, s.description "
            "FROM symbols_fts f JOIN symbols s ON s.rowid = f.rowid "
            "WHERE symbols_fts MATCH ? ORDER BY bm25(symbols_fts) LIMIT ?"
        )
        try:
            return list(store.conn.execute(sql, (text, limit)))
        except Exception:
            pass
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
    try:
        text = service.format_history(root, symbol, max_depth)
    except FileNotFoundError:
        err_console.print(f"[red]{service.NO_INDEX_MSG}[/red]")
        raise typer.Exit(2)
    if text.startswith("No history for"):
        console.print(f"[yellow]{text}[/yellow]")
        return
    # EN: render as plain print per line for styling parity with before.
    # ZH: 逐行纯输出，与原有样式保持一致。
    for line in text.splitlines():
        if line.startswith("## "):
            console.rule(f"[bold]{line[3:]}")
        elif line.strip() and not line.startswith(("  ", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0")):
            console.print(f"[dim]{line}[/dim]")
        else:
            console.print(line)


def _print_history(store: Store, symbol: str, max_depth: int) -> None:
    """Deprecated: use service.format_history (kept for direct callers)."""
    console.print(service.format_history_from_store(store, symbol, max_depth))


# ==========================================================================
# EN: context command group — LLM context virtual memory surface.
# ZH: context 命令组 —— LLM 上下文虚拟内存入口。
# ==========================================================================

context_app = typer.Typer(help="LLM context virtual memory: load/status/evict/budget.", no_args_is_help=True)
app.add_typer(context_app, name="context")


# ==========================================================================
# EN: plan command group — Markdown plan artifact surface.
# ZH: plan 命令组 —— Markdown 计划工件入口。
# ==========================================================================

plan_app = typer.Typer(help="Create, inspect, and lint Markdown plan artifacts.", no_args_is_help=True)
app.add_typer(plan_app, name="plan")


@plan_app.command("context")
def plan_context(
    query: str = typer.Argument(..., help="Natural-language task description."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    limit: int = typer.Option(8, "--limit", min=1, max=32, help="Maximum evidence items."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Kept for command-family consistency; retrieval does not read plan bodies."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Retrieve bounded, evidence-backed context for planning."""
    del plans_dir
    root = path.resolve()
    try:
        payload = service.plan_context(root, query, limit=limit)
    except FileNotFoundError:
        err_console.print(f"[red]{service.NO_INDEX_MSG}[/red]")
        raise typer.Exit(1)
    if json_output:
        _print_json(payload)
        return
    if payload.get("status") == "bootstrap_required":
        console.print(f"[yellow]{payload['hint']}[/yellow]")
        return
    console.print(f"[bold]{payload['query']}[/bold]")
    console.print(payload["summary"])
    table = Table(title="Evidence")
    table.add_column("ID", no_wrap=True)
    table.add_column("Kind", no_wrap=True)
    table.add_column("Ref", overflow="fold")
    table.add_column("Path", overflow="fold")
    table.add_column("Confidence", justify="right")
    table.add_column("Stale", justify="right")
    for item in payload["evidence"]:
        table.add_row(
            item["evidence_id"], item["kind"], item["ref"], item["source_path"],
            f"{item['confidence']:.2f}", "yes" if item["stale"] else "no",
        )
    console.print(table)
    if payload["truncated"]:
        err_console.print("[yellow]Additional ranked evidence was omitted by the retrieval cap.[/yellow]")


@plan_app.command("new")
def plan_new(
    slug: str = typer.Argument(..., help="Short plan slug, e.g. auth-refactor."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    title: str | None = typer.Option(None, "--title", help="Human-readable plan title."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON instead of text."),
) -> None:
    """Create a new valid plan skeleton without overwriting existing files."""
    root = path.resolve()
    if not root.is_dir():
        err_console.print(f"[red]Not a directory: {root}[/red]")
        raise typer.Exit(2)
    try:
        directory = _plans_dir(root, plans_dir)
        result = create_plan(root, directory, slug=slug, title=title)
        plan = result.plan
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)

    payload = {
        "id": plan.id,
        "path": plan.source_path,
        "revision": plan.frontmatter["revision"],
        "content_hash": plan.frontmatter["content_hash"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[green]Created plan[/green] {plan.id} -> {payload['path']}")


@plan_app.command("impact")
def plan_impact(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    changed_file: list[Path] = typer.Option([], "--changed-file", help="Repository-relative changed file; repeatable."),
    changed_symbol: list[str] = typer.Option([], "--changed-symbol", help="Qualified changed symbol; repeatable."),
    max_items: int = typer.Option(200, "--max-items", min=1, max=1000, help="Maximum impact items."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Report bounded read-only impact for one durable plan."""
    root = path.resolve()
    try:
        payload = service.plan_impact(
            root,
            plan_id,
            changed_files=[str(item) for item in changed_file],
            changed_symbols=list(changed_symbol),
            plans_dir=plans_dir,
            max_items=max_items,
        )
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)

    if json_output:
        _print_json(payload)
        return

    if not payload["items"]:
        console.print("[green]No plan impact detected.[/green]")
    else:
        table = Table(title=f"Plan impact: {payload['plan_id']}")
        table.add_column("Level", no_wrap=True)
        table.add_column("Batch", no_wrap=True)
        table.add_column("Kind", no_wrap=True)
        table.add_column("Ref", overflow="fold")
        table.add_column("Path", overflow="fold")
        table.add_column("Task", justify="right")
        table.add_column("Confidence", justify="right")
        for item in payload["items"]:
            table.add_row(
                item["level"], item["batch"], item["kind"], item["ref"],
                item["source_path"] or "-",
                "-" if item.get("task") is None else str(item["task"]),
                f"{item['confidence']:.2f}",
            )
        console.print(table)
    for warning in payload["warnings"]:
        err_console.print(f"[yellow]{warning['code']}: {warning['message']}[/yellow]")
    if payload["truncated"]:
        err_console.print("[yellow]Impact output was truncated by the item cap.[/yellow]")


@plan_app.command("show")
def plan_show(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    view: str = typer.Option("summary", "--view", help="Bounded view: summary, execution, engineering, evidence, graph, or full."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON instead of text."),
) -> None:
    """Show a bounded plan summary or structured full view."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        plan = find_plan(plan_id, directory, root=root)
        payload = plan_view(plan, view=view)
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(exc.code in {"PLAN_NOT_FOUND", "PLAN_DUPLICATE_ID"} and 1 or 1)

    if json_output:
        _print_json(payload)
    elif view == "summary":
        console.print(f"[bold]{payload['id']}[/bold] ({payload['status']}, rev {payload['revision']})")
        console.print(f"profile: {payload['engineering_profile']}  next: {payload['next_batch']}")
        for warning in payload["warnings"]:
            err_console.print(f"[yellow]{warning['code']}: {warning['message']}[/yellow]")
    elif view != "full":
        _print_json(payload)
    else:
        console.print(plan.body)


@plan_app.command("stale")
def plan_stale(
    path: Path = typer.Argument(Path("."), help="Project root."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
    all_plans: bool = typer.Option(False, "--all", help="Include historical plan evidence for audit."),
) -> None:
    """Detect stale gate evidence without rewriting plans."""
    root = path.resolve()
    try:
        payload = detect_stale_evidence(root, _plans_dir(root, plans_dir), include_all=all_plans)
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)
    if json_output:
        _print_json(payload)
        return
    if not payload["items"]:
        scope = "active or historical" if all_plans else "active"
        console.print(f"[green]No stale {scope} plan evidence detected.[/green]")
    for item in payload["items"]:
        console.print(f"[yellow]{item['plan_id']} · {item['batch']} · {item['gate_id']}[/yellow]")


@plan_app.command("approve")
def plan_approve(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    approved_by: str = typer.Option(..., "--approved-by", help="The human approver recorded in the audit event."),
    basis: str = typer.Option("conversation", "--basis", help="conversation, review-doc, issue, or ci-review."),
    notes: str | None = typer.Option(None, "--notes", help="Optional durable approval notes."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject approval if the revision changed."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Record a human approval decision with a revision snapshot."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        result = approve_plan(
            root,
            directory,
            plan_id,
            approved_by=approved_by,
            basis=basis,
            notes=notes,
            expected_revision=expected_revision,
        )
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)

    plan = result.plan
    payload = {
        "id": plan.id,
        "status": plan.status,
        "revision": plan.frontmatter["revision"],
        "reapproval_required": plan.frontmatter["reapproval_required"],
        "content_hash": plan.frontmatter["content_hash"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[green]Approved plan[/green] {plan.id} at revision {payload['revision']}")


@plan_app.command("revise")
def plan_revise(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject revision if the revision changed."),
    allow_stale: bool = typer.Option(False, "--allow-stale", help="Accept externally edited Markdown and refresh the hash."),
    bootstrap: bool = typer.Option(False, "--bootstrap", help="Create a revision 1 baseline for a pre-workflow plan."),
    reason: str | None = typer.Option(None, "--reason", help="Optional durable revision reason."),
    writer: str = typer.Option("codex", "--writer", help="The actor recorded in the audit event."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Record the current Markdown file as the next durable revision."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        result = revise_plan(
            root,
            directory,
            plan_id,
        expected_revision=expected_revision,
        allow_stale=allow_stale,
        bootstrap=bootstrap,
        reason=reason,
            writer=writer,
        )


    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)

    plan = result.plan
    payload = {
        "id": plan.id,
        "status": plan.status,
        "revision": plan.frontmatter["revision"],
        "revision_type": plan.frontmatter["revision_type"],
        "reapproval_required": plan.frontmatter["reapproval_required"],
        "content_hash": plan.frontmatter["content_hash"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(
            f"[green]Revised plan[/green] {plan.id} at revision {payload['revision']} "
            f"({payload['revision_type']})"
        )


@plan_app.command("reapprove")
def plan_reapprove(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    approved_by: str = typer.Option(..., "--approved-by", help="The human approver recorded in the audit event."),
    basis: str = typer.Option("conversation", "--basis", help="conversation, review-doc, issue, or ci-review."),
    notes: str | None = typer.Option(None, "--notes", help="Optional durable reapproval notes."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject reapproval if the revision changed."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Record human reapproval after a semantic revision to an approved plan."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        result = reapprove_plan(
            root,
            directory,
            plan_id,
            approved_by=approved_by,
            basis=basis,
            notes=notes,
            expected_revision=expected_revision,
        )
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)

    plan = result.plan
    payload = {
        "id": plan.id,
        "status": plan.status,
        "revision": plan.frontmatter["revision"],
        "reapproval_required": plan.frontmatter["reapproval_required"],
        "content_hash": plan.frontmatter["content_hash"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[green]Reapproved plan[/green] {plan.id} at revision {payload['revision']}")


@plan_app.command("diff")
def plan_diff(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    from_revision: int = typer.Option(..., "--from-revision", help="The older snapshot revision."),
    to_revision: int = typer.Option(..., "--to-revision", help="The newer snapshot revision."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Classify the change between two durable revision snapshots."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        payload = diff_plan(
            root,
            directory,
            plan_id,
            from_revision=from_revision,
            to_revision=to_revision,
        )
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)
    if json_output:
        _print_json(payload)
    else:
        console.print(f"{payload['revision_type']} change: {from_revision} -> {to_revision}")


@plan_app.command("status")
def plan_status_command(
    path: Path = typer.Argument(Path("."), help="Project root."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON instead of text."),
) -> None:
    """Group plans by status without dumping plan bodies."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        payload = plan_status(directory, root=root)
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)

    if json_output:
        _print_json(payload)
        return
    table = Table(title="plan status")
    table.add_column("Status", no_wrap=True)
    table.add_column("Plans", justify="right")
    table.add_column("IDs", overflow="fold")
    for group in payload["groups"]:
        ids = ", ".join(plan["id"] for plan in group["plans"])
        table.add_row(group["status"], str(len(group["plans"])), ids)
    console.print(table)
    for warning in payload["warnings"]:
        err_console.print(f"[yellow]{warning['code']}: {warning['message']}[/yellow]")


@plan_app.command("lint")
def plan_lint(
    path: Path = typer.Argument(Path("."), help="Project root."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON instead of text."),
) -> None:
    """Lint all Markdown plans and return structured stable diagnostics."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        issues = lint_plans(directory, root=root)
    except PlanError as exc:
        issues = [type("LintIssue", (), {"code": exc.code, "message": exc.message, "field": exc.field, "path": exc.path})()]

    payload = {
        "ok": not issues,
        "issues": [
            {"code": issue.code, "message": issue.message, "field": issue.field, "path": issue.path}
            for issue in issues
        ],
    }
    if json_output:
        _print_json(payload)
    elif issues:
        for issue in issues:
            location = f" [{issue.path}]" if issue.path else ""
            err_console.print(f"[red]{issue.code}{location}: {issue.message}[/red]")
    else:
        console.print("[green]All plans passed lint.[/green]")
    if issues:
        raise typer.Exit(1)


def _require_index(path: Path) -> tuple[Path, Store]:
    """Open the store or exit 1 with the standard no-index message (plan v6)."""
    root = path.resolve()
    db = root / ".codeatlas" / "state.db"
    if not db.is_file():
        err_console.print(f"[red]{service.NO_INDEX_MSG}[/red]")
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
    root, _store = _require_index(path)
    try:
        # EN: anchor is written inside load_page AFTER the page resolves —
        # ambiguity/not-found never pollute meta['last_anchor'] (plan v6).
        # ZH: 锚点在 load_page 内部、页面解析成功后才写入 —— 歧义/未找到
        # 不会污染 meta['last_anchor']（方案 v6）。
        try:
            outcome = service.load_context_page(
                root, symbol, granularity, anchor=anchor, pin=pin, with_source=source,
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
    except FileNotFoundError:
        err_console.print(f"[red]{service.NO_INDEX_MSG}[/red]")
        raise typer.Exit(1)

    if outcome.page is None:
        err_console.print(f"[red]Symbol or file not found: {symbol}[/red]")
        raise typer.Exit(1)

    evicted, unsatisfied, tokens, page = outcome.evicted, outcome.unsatisfied, outcome.tokens, outcome.page
    if unsatisfied > 0:
        err_console.print(
            f"[yellow]Warning: {unsatisfied} tokens could not be freed — "
            "consider raising the working-set budget (`context budget --working-set N`).[/yellow]"
        )
    for page_id in evicted:
        err_console.print(f"[dim]evicted: {page_id}[/dim]")

    if json_output:
        import json as _json

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
                    "stale": outcome.stale,
                },
                ensure_ascii=False,
            )
        )
    else:
        # EN: pure print — no rich folding/ANSI; piping is lossless (v6).
        # ZH: 纯 print —— 无 rich 折行/ANSI；管道输出无损（v6）。
        print(outcome.rendered)


@context_app.command("status")
def context_status(
    path: Path = typer.Argument(Path("."), help="Project root."),
) -> None:
    """Show the working set: pages, tokens, recency, stale/gone, budget bar."""
    root, _store = _require_index(path)
    try:
        text = service.format_status(root)
    except FileNotFoundError:
        err_console.print(f"[red]{service.NO_INDEX_MSG}[/red]")
        raise typer.Exit(1)
    console.print(text)


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
    root, _store = _require_index(path)
    try:
        msg = service.evict_pages(
            root, page_id, all_pages=all_pages, pin=pin, unpin=unpin, force=force,
        )
    except FileNotFoundError:
        err_console.print(f"[red]{service.NO_INDEX_MSG}[/red]")
        raise typer.Exit(1)
    except KeyError as e:
        err_console.print(f"[red]{e.args[0]}[/red]")
        raise typer.Exit(1)
    except PermissionError as e:
        err_console.print(f"[yellow]{e.args[0]}[/yellow]")
        raise typer.Exit(1)
    except ValueError as e:
        err_console.print(f"[red]{e.args[0]}[/red]")
        raise typer.Exit(2)
    console.print(f"[green]{msg}[/green]")


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
    root, _store = _require_index(path)
    store = Store(root / ".codeatlas" / "state.db")
    try:
        from .memory import render_working_set

        print(render_working_set(store, lang))
    finally:
        store.close()


@app.command()
def doctor(
    path: Path = typer.Argument(Path("."), help="Project root."),
) -> None:
    """Run consistency invariants; exit 1 on violations."""
    root, _store = _require_index(path)
    try:
        problems = service.doctor_problems(root)
        store = Store(root / ".codeatlas" / "state.db")
        try:
            rate_raw = store.get_meta("call_resolution_rate")
        finally:
            store.close()
        if rate_raw:
            console.print(f"[dim]call resolution rate: {float(rate_raw):.0%}[/dim]")
    except FileNotFoundError:
        err_console.print(f"[red]{service.NO_INDEX_MSG}[/red]")
        raise typer.Exit(1)

    for warning in service.doctor_warnings(root):
        err_console.print(f"[yellow]{warning}[/yellow]")

    if problems:
        for p in problems:
            err_console.print(f"[red]✗[/red] {p}")
        raise typer.Exit(1)
    console.print("[green]All consistency checks passed. / 一致性检查全部通过。[/green]")


@app.command()
def serve(
    lsp: bool = typer.Option(False, "--lsp", help="Run in LSP mode (placeholder shape)."),
) -> None:
    """Run the MCP server (stdio); LSP mode is planned for a later phase."""
    if lsp:
        console.print(
            "[yellow]LSP server is planned for a later phase. / LSP 服务器计划于后续阶段实现。[/yellow]"
        )
        raise typer.Exit(0)
    from .mcp_server import main as mcp_main

    mcp_main()


@app.command()
def mcp() -> None:
    """Run the MCP server (stdio transport) for AI agent integration."""
    from .mcp_server import main as mcp_main

    mcp_main()


@app.command()
def version() -> None:
    """Print the CodeAtlas version."""
    console.print(f"codeatlas {__version__}")


batch_app = typer.Typer(help="Start, complete, reopen, and invalidate validated plan batches.", no_args_is_help=True)
gate_app = typer.Typer(help="Run and record plan quality gates.", no_args_is_help=True)
plan_app.add_typer(batch_app, name="batch")
plan_app.add_typer(gate_app, name="gate")


@batch_app.command("start")
def plan_batch_start(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    batch: str = typer.Argument(..., help="Batch ID from the Batches table."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    actor: str = typer.Option("codex", "--actor", help="Actor recorded in the audit event."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject the transition if the revision changed."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Start one pending or blocked batch."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        result = start_batch(root, directory, plan_id, batch=batch, expected_revision=expected_revision, actor=actor)
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)
    payload = {
        "id": result.plan.id,
        "batch": batch,
        "status": result.plan.status,
        "revision": result.plan.frontmatter["revision"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[green]Started batch[/green] {batch} at revision {payload['revision']}")


@batch_app.command("complete")
def plan_batch_complete(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    batch: str = typer.Argument(..., help="Batch ID from the Batches table."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    actor: str = typer.Option("codex", "--actor", help="Actor recorded in the audit event."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject the transition if the revision changed."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Complete a batch after required gate and test evidence pass."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        result = complete_batch(root, directory, plan_id, batch=batch, expected_revision=expected_revision, actor=actor)
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)
    payload = {
        "id": result.plan.id,
        "batch": batch,
        "status": result.plan.status,
        "revision": result.plan.frontmatter["revision"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[green]Completed batch[/green] {batch} at revision {payload['revision']}")


@gate_app.command("run")
def plan_gate_run(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    batch: str = typer.Argument(..., help="Batch ID that this gate run validates."),
    gate_id: str = typer.Argument(..., help="Configured gate ID."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    actor: str = typer.Option("trusted-runner", "--actor", help="Actor recorded for runner evidence."),
    timeout: float = typer.Option(60.0, "--timeout", help="Gate timeout in seconds."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject if the revision changed before running."),
    show_output: bool = typer.Option(False, "--show-output", help="Include a bounded output excerpt."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Run a configured argv command gate and record its evidence."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        plan = find_plan(plan_id, directory, root=root)
        definition = find_gate_definition(plan, gate_id)
        outcome = run_gate(definition, root=root, timeout_seconds=timeout)
        result = record_gate_result(
            root,
            directory,
            plan_id,
            gate_id=gate_id,
            outcome=outcome["outcome"],
            actor=actor,
            evidence_kind="runner",
            batch=batch,
            expected_revision=expected_revision if expected_revision is not None else int(plan.frontmatter["revision"]),
            output_digest=outcome["output_digest"],
            reason=outcome.get("reason"),
        )
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)
    payload = {
        "id": result.plan.id,
        "batch": batch,
        "gate_id": gate_id,
        "outcome": outcome["outcome"],
        "exit_code": outcome["exit_code"],
        "revision": result.plan.frontmatter["revision"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if show_output:
        payload["output_excerpt"] = outcome["output_excerpt"][:2000]
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[green]Recorded gate[/green] {gate_id}: {outcome['outcome']}")
    if outcome["outcome"] != "passed":
        raise typer.Exit(1)


@gate_app.command("review")
def plan_gate_review(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    batch: str = typer.Argument(..., help="Batch ID that this review validates."),
    gate_id: str = typer.Argument(..., help="Configured gate ID."),
    artifact: str = typer.Argument(..., help="Path or URL of the review artifact."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    outcome: str = typer.Option("passed", "--outcome", help="passed, failed, or not-run."),
    actor: str = typer.Option(..., "--actor", help="Human reviewer recorded as evidence."),
    reason: str | None = typer.Option(None, "--reason", help="Required for failed or not-run outcomes."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject if the revision changed."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Record durable review evidence for a review gate."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        result = record_gate_result(
            root,
            directory,
            plan_id,
            gate_id=gate_id,
            outcome=outcome,
            actor=actor,
            evidence_kind="review",
            batch=batch,
            expected_revision=expected_revision,
            artifact=artifact,
            reason=reason,
        )
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)
    payload = {
        "id": result.plan.id,
        "batch": batch,
        "gate_id": gate_id,
        "outcome": outcome,
        "revision": result.plan.frontmatter["revision"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[green]Recorded review[/green] {gate_id}: {outcome}")


@batch_app.command("stale")
def plan_batch_stale(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    batch: str = typer.Argument(..., help="Batch ID from the Batches table."),
    reason: str = typer.Option(..., "--reason", help="Why the recorded evidence no longer applies."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    actor: str = typer.Option("codex", "--actor", help="Actor recorded in the audit event."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject the transition if the revision changed."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Mark a passed batch stale without reopening the plan status."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        result = mark_batch_stale(
            root,
            directory,
            plan_id,
            batch=batch,
            reason=reason,
            expected_revision=expected_revision,
            actor=actor,
        )
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)
    payload = {
        "id": result.plan.id,
        "batch": batch,
        "status": result.plan.status,
        "revision": result.plan.frontmatter["revision"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[yellow]Marked batch stale[/yellow] {batch} at revision {payload['revision']}")


@batch_app.command("reopen")
def plan_batch_reopen(
    plan_id: str = typer.Argument(..., help="Durable plan ID from frontmatter."),
    batch: str = typer.Argument(..., help="Batch ID from the Batches table."),
    path: Path = typer.Argument(Path("."), help="Project root."),
    reason: str = typer.Option(..., "--reason", help="Why the stale batch needs fresh validation."),
    actor: str = typer.Option("codex", "--actor", help="Actor recorded in the audit event."),
    expected_revision: int | None = typer.Option(None, "--expected-revision", help="Reject the transition if the revision changed."),
    plans_dir: Path = typer.Option(Path("docs/plans"), "--plans-dir", help="Plans directory relative to the project root."),
    json_output: bool = typer.Option(False, "--json", help="Emit deterministic JSON."),
) -> None:
    """Reopen a stale batch in a done plan for fresh validation."""
    root = path.resolve()
    try:
        directory = _plans_dir(root, plans_dir)
        result = reopen_batch(
            root,
            directory,
            plan_id,
            batch=batch,
            reason=reason,
            expected_revision=expected_revision,
            actor=actor,
        )
    except PlanError as exc:
        err_console.print(f"[red]{exc.code}: {exc.message}[/red]")
        raise typer.Exit(1)
    payload = {
        "id": result.plan.id,
        "batch": batch,
        "status": result.plan.status,
        "revision": result.plan.frontmatter["revision"],
        "snapshot_path": result.snapshot_path.relative_to(root).as_posix(),
    }
    if json_output:
        _print_json(payload)
    else:
        console.print(f"[yellow]Reopened batch[/yellow] {batch} at revision {payload['revision']}")


def main() -> None:
    """Console-script entry point."""
    app()


if __name__ == "__main__":
    main()
