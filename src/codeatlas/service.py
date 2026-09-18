"""EN: Shared service layer — orchestration used by both the CLI and the MCP
server. No rich, no Typer, no stdout printing: returns plain data/text so the
MCP stdio channel (JSON-RPC owns stdout) stays clean.

ZH: 共享服务层 —— CLI 与 MCP server 共用的编排逻辑。不依赖 rich/Typer，
不向 stdout 打印：返回纯数据/文本，保证 MCP stdio 通道（stdout 归
JSON-RPC 独占）不被污染。

EN: Concurrency contract: every function opens its own Store and closes it
before returning (sqlite3 connections are not shareable across threads, and
the MCP SDK runs sync tools in a worker pool). Per-call stores are cheap:
WAL is enabled and the schema is already applied.
ZH: 并发约定：每个函数自建 Store 并在返回前关闭（sqlite3 连接不能跨线程
共享，而 MCP SDK 的同步 tool 在线程池里并发执行）。按调用建 Store 开销
很小：已开 WAL、schema 建好即用。
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path

from . import memory
from .changelog import write_codeatlas_gitignore, write_history_doc
from .consistency import run_all_checks
from .indexer import run_scan, run_update
from .markdown import render_detail_files, render_overview
from .memory import AmbiguousSymbol, load_page, page_cost  # noqa: F401 (re-export)
from .models import Page
from .plan_memory import (
    ACTIVE_PLAN_STATUSES,
    detect_stale_evidence,
    load_plan_state_config,
    plan_doctor_problems,
    plan_doctor_warnings,
    write_stale_report,
)
from .plan_context import retrieve_plan_context
from .plan_impact import compute_plan_impact, write_update_impact_report
from .plan_workflow import mark_batch_stale
from .plans import PlanError, find_plan
from .prefetch import prefetch as do_prefetch
from .storage import Store

NO_INDEX_MSG = (
    "No index found. Run `codeatlas scan .` first. / 未找到索引，请先运行 `codeatlas scan .`"
)


@dataclass
class UpdateOutcome:
    """Result of one update_project call (service-level, renderer-agnostic)."""

    result: object  # indexer.ScanResult
    fell_back: bool  # no state.db -> a full scan ran instead
    history_path: Path | None
    language_switched: bool  # stored output lang differed; full re-scan done
    impact_report_path: Path | None = None
    impact_report: dict | None = None
    plan_state_report: dict | None = None


# ---------------------------------------------------------------- store helpers

def open_store(root: Path) -> Store:
    """Open (creating if needed) the .codeatlas/state.db for a project root."""
    codeatlas_dir = root / ".codeatlas"
    codeatlas_dir.mkdir(parents=True, exist_ok=True)
    return Store(codeatlas_dir / "state.db")


def _mark_stale_passed_batches(root: Path, plans_dir: Path, stale_report: dict) -> dict:
    """Mark passed batches stale through the canonical plan workflow."""
    root_path = root.resolve()
    groups: dict[tuple[str, str], list[dict]] = {}
    for item in stale_report.get("items", []):
        key = (str(item.get("plan_id", "")), str(item.get("batch", "")))
        groups.setdefault(key, []).append(item)

    marked: list[dict] = []
    skipped: list[dict] = []
    for (plan_id, batch), items in sorted(groups.items()):
        gates = sorted({str(item.get("gate_id", "")) for item in items if str(item.get("gate_id", "")).strip()})
        try:
            plan = find_plan(plan_id, plans_dir, root=root_path)
        except PlanError as exc:
            skipped.append(
                {
                    "batch": batch,
                    "code": exc.code,
                    "message": exc.message,
                    "plan_id": plan_id,
                }
            )
            continue
        row = next((entry for entry in plan.batches if str(entry.get("batch", "")) == batch), None)
        if plan.status not in ACTIVE_PLAN_STATUSES:
            skipped.append(
                {
                    "batch": batch,
                    "code": "PLAN_NOT_ACTIVE",
                    "message": "Update-time stale marking only applies to active plans.",
                    "plan_id": plan_id,
                }
            )
            continue
        if row is None or str(row.get("status", "")) != "passed":
            skipped.append(
                {
                    "batch": batch,
                    "code": "BATCH_NOT_PASSED",
                    "message": "Only a passed batch is eligible for update-time stale marking.",
                    "plan_id": plan_id,
                }
            )
            continue
        try:
            result = mark_batch_stale(
                root_path,
                plans_dir,
                plan_id,
                batch=batch,
                reason="Update changed declared batch inputs; gate fingerprints no longer match: "
                + (", ".join(gates) if gates else "unknown gates"),
                actor="codeatlas-update",
            )
        except PlanError as exc:
            skipped.append(
                {
                    "batch": batch,
                    "code": exc.code,
                    "message": exc.message,
                    "plan_id": plan_id,
                }
            )
            continue
        marked.append(
            {
                "batch": batch,
                "gates": gates,
                "plan_id": plan_id,
                "revision": int(result.plan.frontmatter["revision"]),
                "snapshot_path": result.snapshot_path.relative_to(root_path).as_posix(),
            }
        )
    return {"allow_update_plan_state": True, "marked": marked, "skipped": skipped}


def require_store(root: Path) -> Store:
    """Open the store or raise FileNotFoundError when there is no index yet."""
    db = root / ".codeatlas" / "state.db"
    if not db.is_file():
        raise FileNotFoundError(NO_INDEX_MSG)
    return Store(db)


def resolve_root(root: str | Path | None) -> Path:
    """Resolve the project root for MCP tools: arg > CODEATLAS_ROOT env > CWD.

    EN: MCP clients start the server with an arbitrary CWD; the env var lets
    users pin the workspace in mcp.json. Must be an existing directory.
    ZH: MCP 客户端以任意 CWD 启动 server；env 变量允许在 mcp.json 里固定
    工作区。必须是存在的目录。
    """
    if root is not None:
        path = Path(root)
    else:
        env = os.environ.get("CODEATLAS_ROOT")
        path = Path(env) if env else Path.cwd()
    path = path.resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"Not a directory: {path}")
    return path


# ---------------------------------------------------------------- scan / update

def scan_project(root: Path, lang: str = "en", max_tokens: int | None = None):
    """Full scan + render overview/detail/gitignore. Returns indexer.ScanResult."""
    store = open_store(root)
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
    return result


def update_project(root: Path, lang: str = "en", max_tokens: int | None = None) -> UpdateOutcome:
    """Incremental update + render overview/detail + history doc.

    EN: falls back to a full scan when no state.db exists (same UX as the
    CLI). A language switch signals via files_skipped == -1; we zero it here
    and report it on the outcome so callers can notify uniformly.
    ZH: 无状态库时退化为全量 scan（与 CLI 体验一致）。语言切换经
    files_skipped == -1 哨兵传递；此处归零并在 outcome 上报告，调用方
    统一提示。
    """
    db = root / ".codeatlas" / "state.db"
    if not db.is_file():
        result = scan_project(root, lang, max_tokens)
        return UpdateOutcome(result=result, fell_back=True, history_path=None, language_switched=False)

    store = Store(db)
    try:
        result = run_update(root, store, output_lang=lang)
        switched = result.files_skipped == -1
        if switched:
            result.files_skipped = 0
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
        plans_dir = root / "docs" / "plans"
        stale_report = detect_stale_evidence(root, plans_dir)
        plan_state_config = load_plan_state_config(root)
        if plan_state_config["allow_update_plan_state"]:
            plan_state_report = _mark_stale_passed_batches(root, plans_dir, stale_report)
        else:
            plan_state_report = {
                "allow_update_plan_state": False,
                "marked": [],
                "skipped": [
                    {
                        "batch": str(item.get("batch", "")),
                        "code": "PLAN_STATE_WRITE_DISABLED",
                        "message": "Plan-state writing is disabled; run the canonical stale workflow explicitly.",
                        "plan_id": str(item.get("plan_id", "")),
                    }
                    for item in stale_report.get("items", [])
                ],
            }
        write_stale_report(root, plans_dir)
        changed_files = sorted({str(change.file) for change in result.changes})
        changed_symbols = sorted({str(change.symbol) for change in result.changes})
        source_paths_by_symbol = {
            str(change.symbol): str(change.file) for change in result.changes
        }
        impact_report_path = write_update_impact_report(
            root,
            changed_files=changed_files,
            changed_symbols=changed_symbols,
            source_paths_by_symbol=source_paths_by_symbol,
            plans_dir=root / "docs" / "plans",
        )
        impact_report = json.loads(impact_report_path.read_text(encoding="utf-8"))
    finally:
        store.close()
    return UpdateOutcome(
        result=result, fell_back=False, history_path=history_path, language_switched=switched,
        impact_report_path=impact_report_path,
        impact_report=impact_report,
        plan_state_report=plan_state_report,
    )


# ---------------------------------------------------------------- search

def search_symbols(root: Path, text: str, limit: int = 20) -> list[dict]:
    """Symbol search: FTS5 bm25 (>=3 chars) with a ranked LIKE fallback.

    EN: moved verbatim from the CLI `_search` so CLI and MCP cannot drift.
    Raises FileNotFoundError when there is no index.
    ZH: 自 CLI `_search` 原样迁移，避免 CLI 与 MCP 漂移。无索引时抛
    FileNotFoundError。
    """
    store = require_store(root)
    try:
        if store.fts_enabled and len(text) >= 3:
            sql = (
                "SELECT s.file, s.line, s.qualified_name, s.signature, s.description "
                "FROM symbols_fts f JOIN symbols s ON s.rowid = f.rowid "
                "WHERE symbols_fts MATCH ? ORDER BY bm25(symbols_fts) LIMIT ?"
            )
            try:
                rows = list(store.conn.execute(sql, (text, limit)))
                return [_search_row(r) for r in rows]
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
        rows = list(
            store.conn.execute(sql, {"t": text, "p": f"{text}%", "l": like, "lim": limit})
        )
        return [_search_row(r) for r in rows]
    finally:
        store.close()


def _search_row(row: tuple) -> dict:
    return {
        "file": row[0],
        "line": row[1],
        "qualified_name": row[2],
        "signature": row[3],
        "description": row[4],
    }


def plan_context(root: Path, query: str, *, limit: int = 8, max_tokens: int = 4_000) -> dict:
    """Retrieve bounded plan context; query text is data, never code."""
    return retrieve_plan_context(root, query, max_evidence=limit, max_tokens=max_tokens)


def plan_impact(
    root: Path,
    plan_id: str,
    *,
    changed_files: list[str] | None = None,
    changed_symbols: list[str] | None = None,
    source_paths_by_symbol: dict[str, str] | None = None,
    plans_dir: str | Path = "docs/plans",
    max_items: int = 200,
    use_index: bool = True,
) -> dict:
    """Compute bounded, read-only impact for one durable plan."""
    return compute_plan_impact(
        root,
        plan_id,
        changed_files=changed_files,
        changed_symbols=changed_symbols,
        source_paths_by_symbol=source_paths_by_symbol,
        plans_dir=plans_dir,
        max_items=max_items,
        use_index=use_index,
    )


# ---------------------------------------------------------------- history

def format_history(root: Path, symbol: str, max_depth: int = 5) -> str:
    """A symbol's evolution chain as plain text (renames followed).

    EN: mirrors the CLI `_print_history` chain logic without rich markup.
    Bare names that match nothing return an explanatory line; bare names
    matching several qualified symbols list all of them.
    ZH: 对应 CLI `_print_history` 的链条逻辑，无 rich 标记。裸名无命中
    返回说明行；命中多个限定名时全部列出。
    """
    store = require_store(root)
    try:
        return _format_history_store(store, symbol, max_depth)
    finally:
        store.close()


def format_history_from_store(store: Store, symbol: str, max_depth: int = 5) -> str:
    """Variant taking an already-open Store (CLI deprecated helper)."""
    return _format_history_store(store, symbol, max_depth)


def _format_history_store(store: Store, symbol: str, max_depth: int) -> str:
    lines: list[str] = []
    if "." in symbol:
        names = [symbol]
    else:
        counts = store.changes_by_symbol_name(symbol)
        if not counts:
            return f"No history for '{symbol}'. / 无 '{symbol}' 的历史记录。"
        names = sorted(counts)
        if len(names) > 1:
            lines.append(f"{len(names)} qualified symbols match '{symbol}':")

    seen: set[str] = set()
    for name in names:
        lines.append(f"## {name}")
        depth = 0
        current = name
        while current and current not in seen and depth <= max_depth:
            seen.add(current)
            records = store.changes_for_symbol(current)
            if not records:
                break
            for rec in records:
                detail = f" [{rec.detail}]" if rec.detail else ""
                lines.append(
                    f"  {rec.ts} {rec.change_type.value} "
                    f"old={rec.old_value!r} new={rec.new_value!r}{detail}"
                )
            renamed_to = next(
                (r.new_value for r in records if r.change_type.value == "renamed"), None
            )
            current = renamed_to
            depth += 1
    return "\n".join(lines)


# ---------------------------------------------------------------- context VM


def context_scope_key(session_id: str = "", plan_id: str = "", batch_id: str = "") -> str:
    """Return the bounded, deterministic identity of one context scope."""
    return json.dumps(
        [session_id, plan_id, batch_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass
class ContextLoadOutcome:
    """Everything a `context load` caller needs, computed while the store was open."""

    page: Page  # models.Page; None when nothing matched
    rendered: str  # store-aware markdown render
    evicted: list[str]
    unsatisfied: int  # tokens that could not be freed
    tokens: int  # page_cost(page)
    stale: bool  # file changed since the page was built


def load_context_page(
    root: Path,
    symbol: str,
    granularity: str | None = None,
    anchor: int | None = None,
    pin: bool = False,
    with_source: bool = False,
    session_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
) -> ContextLoadOutcome:
    """Load one page into the working set; enforce budget; prefetch neighbours.

    EN: single entry for CLI `context load` and the MCP context_load tool.
    Rendering, cost, staleness are computed while the store is open (file
    pages need it), then the store closes. outcome.page is None when nothing
    matches; AmbiguousSymbol carries the candidate list.
    ZH: CLI `context load` 与 MCP context_load 的唯一入口。渲染、成本、
    staleness 都在 store 未关时算好，随后关闭。无命中时 outcome.page 为
    None；AmbiguousSymbol 携带候选列表。
    """
    store = require_store(root)
    scope_key = context_scope_key(session_id, plan_id, batch_id)
    if not store.acquire_working_set_lease(
        scope_key, store.lease_owner, ttl_seconds=30
    ):
        store.close()
        raise PermissionError(
            f"Context lease is held for scope {scope_key}; retry after it expires."
        )
    try:
        page = load_page(
            store, symbol, granularity, anchor_line=anchor, pin=pin, origin="load",
            with_source=with_source,
            session_id=session_id,
            plan_id=plan_id,
            batch_id=batch_id,
        )
        if page is None:
            return ContextLoadOutcome(
                page=None, rendered="", evicted=[], unsatisfied=0, tokens=0, stale=False
            )
        rendered = memory.render_page_with_store(store, page)
        tokens = page_cost(page)
        evicted, unsatisfied = memory.ensure_budget(
            store,
            session_id=session_id,
            plan_id=plan_id,
            batch_id=batch_id,
        )
        do_prefetch(
            store,
            page,
            session_id=session_id,
            plan_id=plan_id,
            batch_id=batch_id,
        )
        current_hash = store.get_file_hash(page.file)
        return ContextLoadOutcome(
            page=page,
            rendered=rendered,
            evicted=evicted,
            unsatisfied=unsatisfied,
            tokens=tokens,
            stale=bool(current_hash and current_hash != page.version),
        )
    finally:
        store.release_working_set_lease(scope_key, store.lease_owner)
        store.close()


def context_page_json(root: Path, symbol: str, **kwargs) -> dict:
    """JSON shape of one context load (CLI --json and MCP consumers)."""
    outcome = load_context_page(root, symbol, **kwargs)
    if outcome.page is None:
        return {"error": "not_found"}
    p = outcome.page
    return {
        "page": {
            "page_id": p.page_id,
            "granularity": p.granularity,
            "file": p.file,
            "line": p.line,
            "end_line": p.end_line,
            "signature": p.signature,
            "callers": p.callers,
            "callees": p.callees,
            "related_files": p.related_files,
        },
        "tokens": outcome.tokens,
        "stale": outcome.stale,
    }


def format_status(root: Path, session_id: str = "", plan_id: str = "", batch_id: str = "") -> str:
    """Working-set status as a plain-text table (no ANSI/rich).

    EN: MCP-safe rendering of memory.status + budget bar + the >40% eviction
    advice from the CLI.
    ZH: memory.status + 预算条 + CLI 的 >40% 淘汰率建议，纯文本渲染
    （无 ANSI/rich，MCP 安全）。
    """
    store = require_store(root)
    try:
        rows = memory.status(
            store,
            session_id=session_id,
            plan_id=plan_id,
            batch_id=batch_id,
        )
        b = memory.load_budget(store)
        total_tokens = sum(r.tokens for r in rows)

        header = (
            f"{'page':<50} {'gran':<8} {'tokens':>7}  {'last access':<19} "
            f"{'ver':<12} {'state':<6} flags"
        )
        lines = [header, "-" * len(header)]
        for r in rows:
            ver = f"{r.loaded_index_version}/{r.current_index_version}" if r.loaded_index_version else "-"
            flags = []
            if r.pinned:
                flags.append("pinned")
            if r.origin == "prefetch":
                flags.append("prefetch")
            last = r.last_access_at[:19].replace("T", " ")
            lines.append(
                f"{r.page_id:<50.50} {r.granularity:<8} {r.tokens:>7}  {last:<19} "
                f"{ver:<12} {r.state:<6} {','.join(flags) if flags else '-'}"
            )
        pct = min(1.0, total_tokens / b.total) if b.total else 0.0
        pages_note = f"pages {len(rows)}/{b.max_pages}" + (" (over)" if len(rows) > b.max_pages else "")
        lines.append("")
        lines.append(
            f"budget: {total_tokens}/{b.total} tokens ({pct:.0%}) - {pages_note}"
        )
        if store.evict_count() > 0:
            ratio = store.evict_count() / b.max_pages if b.max_pages else 0
            if ratio > 0.4:
                lines.append(
                    f"warning: {store.evict_count()} page(s) evicted (>40% of max-pages) — "
                    "consider raising the budget (`context budget --working-set N --max-pages M`)"
                )
        return "\n".join(lines)
    finally:
        store.close()


def evict_pages(
    root: Path,
    page_id: str | None,
    all_pages: bool = False,
    pin: bool = False,
    unpin: bool = False,
    force: bool = False,
    session_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
) -> str:
    """Evict / pin / unpin working-set pages; returns a plain-text outcome.

    EN: mirrors the CLI `context evict` semantics: pin/unpin single pages,
    `--all` keeps pinned unless force, single-page evict refuses pinned
    unless force.
    ZH: 对应 CLI `context evict` 语义：pin/unpin 单页；`--all` 默认保留
    pinned（force 例外）；单页淘汰遇 pinned 需 force。
    """
    store = require_store(root)
    scope_key = context_scope_key(session_id, plan_id, batch_id)
    if not store.acquire_working_set_lease(
        scope_key, store.lease_owner, ttl_seconds=30
    ):
        store.close()
        raise PermissionError(
            f"Context lease is held for scope {scope_key}; retry after it expires."
        )
    try:
        if pin or unpin:
            target = page_id
            entry = store.get_working_set_entry(
                target,
                session_id=session_id,
                plan_id=plan_id,
                batch_id=batch_id,
            )
            if entry is None:
                raise KeyError(f"Not in working set: {target}")
            entry.pinned = pin and True or (False if unpin else entry.pinned)
            store.upsert_working_set(entry)
            return f"{'pinned' if pin else 'unpinned'} {target}"
        if all_pages:
            entries = memory.entries_for_scope(
                store,
                session_id=session_id,
                plan_id=plan_id,
                batch_id=batch_id,
            )
            if not force:
                entries = [e for e in entries if not e.pinned]
            # EN: with force, bypass memory.evict — it never evicts pinned
            # pages by design, so `--all --force` would silently no-op on
            # them (a latent CLI bug this service port fixes).
            # ZH: force 时绕过 memory.evict —— 它按设计永不淘汰 pinned 页，
            # 否则 `--all --force` 对 pinned 页会静默无效（此处修复 CLI 的
            # 一个潜在 bug）。
            if force:
                freed = 0
                for e in entries:
                    store.delete_working_set_entry(
                        e.page_id,
                        session_id=e.session_id,
                        plan_id=e.plan_id,
                        batch_id=e.batch_id,
                    )
                    freed += 1
                if freed:
                    store.add_evict_count(freed)
                return f"Evicted {freed} page(s)"
            total = sum(e.tokens for e in entries)
            evicted, _unsat = memory.evict(
                store,
                total,
                session_id=session_id,
                plan_id=plan_id,
                batch_id=batch_id,
            )
            return f"Evicted {len(evicted)} page(s)"
        if not page_id:
            raise ValueError("Provide a page_id or all=True")
        entry = store.get_working_set_entry(
            page_id,
            session_id=session_id,
            plan_id=plan_id,
            batch_id=batch_id,
        )
        if entry is None:
            raise KeyError(f"Not in working set: {page_id}")
        if entry.pinned and not force:
            raise PermissionError("Page is pinned — use force=True to evict.")
        store.delete_working_set_entry(
            page_id,
            session_id=session_id,
            plan_id=plan_id,
            batch_id=batch_id,
        )
        return f"Evicted {page_id}"
    finally:
        store.release_working_set_lease(scope_key, store.lease_owner)
        store.close()


# ---------------------------------------------------------------- doctor

def doctor_problems(root: Path) -> list[str]:
    """Consistency invariants + working-set budget check (doctor core)."""
    store = require_store(root)
    try:
        history_dir = root / ".codeatlas" / "history"
        problems = run_all_checks(store, root, history_dir if history_dir.is_dir() else None)
        problems.extend(plan_doctor_problems(root, root / "docs" / "plans"))
        b = memory.load_budget(store)
        entries = store.working_set_entries()
        used = sum(e.tokens for e in entries)
        if used > b.working_set:
            problems.append(
                f"working set {used} tokens exceeds budget {b.working_set} — run `context evict --all`"
            )
        return problems
    finally:
        store.close()


def doctor_warnings(root: Path) -> list[str]:
    """Return non-fatal consistency warnings that should not block doctor."""
    return plan_doctor_warnings(root, root / "docs" / "plans")
