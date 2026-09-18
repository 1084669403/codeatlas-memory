"""EN: LLM context virtual memory — pages, working set, layered locality,
LRU-flavoured eviction, stale/gone tracking.

ZH: LLM 上下文虚拟内存 —— 页面、工作集、分层 locality、LRU 风格置换、
stale/gone 追踪。

EN: memory depends on budget (one-way); the store is the only source of
truth. Locality is never persisted: it is computed on demand against the
single global anchor meta['last_anchor'] (plan v6) so two processes always
agree on eviction order up to clock skew.
ZH: memory 单向依赖 budget；store 是唯一真相源。locality 不落库：淘汰时
对全局唯一锚点 meta['last_anchor'] 现算（方案 v6），保证多进程下淘汰
排序一致（时钟偏差除外）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from . import budget
from .budget import Budget
from .models import Page, WorkingSetEntry

# EN: source-file suffixes that trigger file-granularity pages.
# ZH: 触发 file 粒度页面的源码后缀。
_SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

# EN: with_source excerpt cap per page (plan P2-6).
# ZH: --source 摘录的每页上限（方案 P2-6）。
SOURCE_TOKEN_CAP = 800

# EN: same-file locality decays to zero over this line distance.
# ZH: 同文件 locality 在该行距内衰减到零。
LOCALITY_WINDOW = 400

# EN: cross-file locality tiers (plan P1-2 layered formula).
# ZH: 跨文件 locality 分层（方案 P1-2 分层公式）。
LOCALITY_RELATED = 0.6  # caller/callee or same directory or file-dependency
LOCALITY_UNRELATED = 0.2


class AmbiguousSymbol(Exception):
    """EN: bare name matched multiple symbols / ZH: 裸名命中多个符号。"""

    def __init__(self, candidates: list[str]) -> None:
        self.candidates = candidates
        super().__init__(f"ambiguous symbol: {len(candidates)} candidates")


def _now_iso() -> str:
    # EN: microsecond precision — LRU ordering needs distinct timestamps.
    # ZH: 微秒精度 —— LRU 排序需要可区分的时间戳。
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _is_file_page(page_id: str) -> bool:
    """File-granularity detection: contains '/' or a known source suffix."""
    return "/" in page_id or page_id.lower().endswith(_SOURCE_SUFFIXES)


def load_budget(store: Store) -> Budget:
    """Read Budget from meta, falling back to defaults."""
    def _get(key: str, default: int) -> int:
        raw = store.get_meta(key)
        try:
            return int(raw) if raw is not None else default
        except ValueError:
            return default

    return Budget(
        total=_get("budget_total", budget.DEFAULT_TOTAL),
        working_set=_get("budget_working_set", budget.DEFAULT_WORKING_SET),
        max_pages=_get("budget_max_pages", budget.DEFAULT_MAX_PAGES),
    )


def save_budget(store: Store, b: Budget) -> None:
    store.set_meta("budget_total", str(b.total))
    store.set_meta("budget_working_set", str(b.working_set))
    store.set_meta("budget_max_pages", str(b.max_pages))


def load_page(
    store: Store,
    page_id: str,
    granularity: str | None = None,
    anchor_line: int | None = None,
    pin: bool = False,
    origin: str = "load",
    with_source: bool = False,
    session_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
) -> Page | None:
    """Load one page into the working set and return it.

    EN: bare names may match several symbols -> AmbiguousSymbol with the
    candidate list (CLI maps that to exit 2). Reloading a resident page is a
    touch: last_access + tokens refresh, counters still bump (plan P1-4).
    Non-empty anchor_line updates the global anchor meta['last_anchor'] (v6).
    ZH: 裸名可能命中多个符号 -> 抛 AmbiguousSymbol 附候选列表（CLI 映射为
    exit 2）。重载驻留页 = touch：刷新 last_access/tokens（方案 P1-4）。
    anchor_line 非空时更新全局锚点 meta['last_anchor']（v6）。
    """
    page = _build_page(store, page_id, granularity, with_source)
    if page is None:
        return None

    if anchor_line is not None:
        store.set_meta("last_anchor", f"{page.file}:{anchor_line}")

    now = _now_iso()
    # EN: snapshot the index version at load time for the status comparison.
    # ZH: 记录加载时刻的索引版本，供 status 对照。
    store.upsert_page(
        page.page_id, page.file, page.version, page.granularity, now,
        index_version=store.index_version(),
    )

    entry = store.get_working_set_entry(
        page.page_id,
        session_id=session_id,
        plan_id=plan_id,
        batch_id=batch_id,
    )
    tokens = page_cost(page)
    if entry is None:
        entry = WorkingSetEntry(
            page_id=page.page_id,
            loaded_at=now,
            last_access_at=now,
            pinned=pin,
            tokens=tokens,
            origin=origin,
            session_id=session_id,
            plan_id=plan_id,
            batch_id=batch_id,
        )
    else:
        # touch: refresh access time and tokens; keep pinned unless upgraded
        entry.last_access_at = now
        entry.tokens = tokens
        if pin:
            entry.pinned = True
        if origin == "load" and entry.origin == "prefetch":
            # EN: a real load upgrades the prefetch origin permanently.
            # ZH: 真实加载永久升级预取来源。
            entry.origin = "load"
    store.upsert_working_set(entry)
    return page


def page_cost(page: Page) -> int:
    """Token cost of one page including per-page overhead."""
    rendered = _render_function_page(page, "en") if page.granularity == "function" else ""
    return budget.page_cost(rendered) if rendered else budget.OVERHEAD


def entries_for_scope(
    store: Store,
    *,
    session_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
) -> list[WorkingSetEntry]:
    """Return working-set entries for one scope.

    EN: no scope selects only the compatibility/global set. A non-empty scope
    filter narrows matching rows and allows broader views (for example, all
    batches in one plan).
    ZH: 无 scope 参数只选择兼容的 global 工作集；非空 scope 字段按条件过滤，
    支持更宽的视图（例如一个 plan 的所有 batch）。
    """
    entries = store.working_set_entries()
    if not session_id and not plan_id and not batch_id:
        return [
            entry
            for entry in entries
            if not (entry.session_id or entry.plan_id or entry.batch_id)
        ]
    return [
        entry
        for entry in entries
        if (not session_id or entry.session_id == session_id)
        and (not plan_id or entry.plan_id == plan_id)
        and (not batch_id or entry.batch_id == batch_id)
    ]


def _build_page(
    store: Store, page_id: str, granularity: str | None, with_source: bool
) -> Page | None:
    """Construct a Page from the store; None when nothing matches."""
    is_file = granularity == "file" or (granularity is None and _is_file_page(page_id))
    if is_file:
        return _build_file_page(store, page_id, with_source)

    row = store.symbol_row(page_id)
    if row is None:
        # bare name? require an exact match on the bare name
        matches = store.symbols_by_name(page_id)
        if not matches:
            return None
        if len(matches) > 1:
            raise AmbiguousSymbol([m[1] for m in matches])
        row = matches[0]

    (
        file,
        qname,
        _name,
        _kind,
        signature,
        _params,
        _returns,
        role,
        line,
        end_line,
        language,
        _bases_json,
        body,
    ) = row

    page = Page(
        page_id=qname,
        granularity="function",
        file=file,
        line=line,
        end_line=end_line,
        signature=signature,
        summary=_symbol_summary(store, qname),
        role=role,
        language=language,
        version=_file_version(store, file),
        callers=store.callers_of(qname),
        callees=store.callees_of(qname),
        related_files=_related_files_for_symbol(store, file),
    )
    if with_source:
        page.source = _source_excerpt(body, page.language)
    return page


def _source_excerpt(body: str, lang: str) -> str:
    """Truncate a body excerpt to SOURCE_TOKEN_CAP tokens."""
    if not body:
        return ""
    lines = body.splitlines()
    out: list[str] = []
    used = 0
    for line_text in lines:
        cost = budget.estimate_tokens(line_text) + 1
        if used + cost > SOURCE_TOKEN_CAP and out:
            break
        out.append(line_text)
        used += cost
    if len(out) < len(lines) and lang == "zh":
        out.append(f"…（截断，共 {len(lines)} 行）")
    elif len(out) < len(lines):
        out.append(f"… (truncated, {len(lines)} lines total)")
    return "\n".join(out)


def _symbol_summary(store: "Store", qname: str) -> str:
    """The enriched description (docstring first line or template)."""
    row = store.conn.execute(
        "SELECT description FROM symbols WHERE qualified_name = ?", (qname,)
    ).fetchone()
    return row[0] if row else ""


def _file_version(store: Store, file: str) -> str:
    return store.get_file_hash(file) or ""


def _related_files_for_symbol(store: Store, file: str) -> list[str]:
    """Files directly imported-imported-by the symbol's file (refs edges)."""
    related = set()
    for src, dst, _sym, _cnt in store.all_refs():
        if src == file:
            related.add(dst)
        elif dst == file:
            related.add(src)
    return sorted(related)


def _build_file_page(store: Store, path: str, with_source: bool) -> Page | None:
    """File-granularity page: file summary + one line per symbol (P1-2)."""
    frow = store.conn.execute(
        "SELECT path, language, role, hash FROM files WHERE path = ?", (path,)
    ).fetchone()
    if frow is None:
        return None
    path, language, role, version = frow
    symbols = store.symbols_for_file_full(path)
    page = Page(
        page_id=path,
        granularity="file",
        file=path,
        line=1,
        end_line=max((s[9] for s in symbols), default=1),
        signature=f"file {path}",
        summary=f"{len(symbols)} symbol(s)",
        role=role,
        language=language,
        version=version,
        related_files=_related_files_for_symbol(store, path),
    )
    if with_source:
        # EN: file pages do not inline bodies; the per-symbol render IS the source.
        # ZH: file 页不内联函数体；逐符号渲染即其"源"。
        page.source = ""
    return page


# ------------------------------------------------------------------ rendering

def render_page(page: Page, lang: str = "en") -> str:
    """Render one page as a markdown block (function or file form).

    EN: output goes through pure print in the CLI (no rich folding/ANSI) so
    piping to files/LLMs is lossless (plan v6). NOTE: file-form rendering
    needs the store; use render_page_with_store for file pages.
    ZH: CLI 用纯 print 输出（无 rich 折行/ANSI），管道输出无损（方案 v6）。
    注意：file 形态渲染需要 store；file 页请用 render_page_with_store。
    """
    if page.granularity == "file":
        # EN: store-less fallback renders only the header; CLI uses the
        # store-aware variant below.
        # ZH: 无 store 的回退只渲染头部；CLI 使用下方带 store 的变体。
        return _render_file_page(None, page, lang)
    return _render_function_page(page, lang)


def render_page_with_store(store: Store, page: Page, lang: str = "en") -> str:
    """Store-aware render: file pages include the per-symbol table."""
    if page.granularity == "file":
        return _render_file_page(store, page, lang)
    return _render_function_page(page, lang)


def _render_function_page(page: Page, lang: str) -> str:
    lines: list[str] = []
    lines.append(f"### `{page.page_id}`")
    lines.append("")
    lines.append(f"- file: `{page.file}` (lines {page.line}-{page.end_line})")
    lines.append(f"- signature: `{page.signature}`")
    lines.append(f"- lang: {page.language} | role: {page.role}")
    if page.summary:
        lines.append(f"- summary: {page.summary}")
    if page.callers:
        lines.append(f"- callers: {', '.join(f'`{c}`' for c in page.callers)}")
    if page.callees:
        lines.append(f"- callees: {', '.join(f'`{c}`' for c in page.callees)}")
    if page.related_files:
        lines.append(f"- related files: {', '.join(f'`{f}`' for f in page.related_files)}")
    if page.source:
        if lang == "zh":
            lines.append("- 摘录 / source:")
        else:
            lines.append("- source excerpt:")
        lines.append("")
        lines.append("```" + (page.language if page.language != "typescript" else "ts"))
        lines.append(page.source)
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _render_file_page(store: "Store | None", page: Page, lang: str) -> str:
    """File-form page: header + one line per symbol (plan P1-2)."""
    lines: list[str] = []
    title = "文件页" if lang == "zh" else "File page"
    lines.append(f"### `{page.page_id}` ({title})")
    lines.append("")
    lines.append(f"- lang: {page.language} | role: {page.role}")
    if page.related_files:
        lines.append(f"- related files: {', '.join(f'`{f}`' for f in page.related_files)}")
    lines.append("")
    if store is not None:
        lines.append("| symbol | lines | signature |")
        lines.append("|---|---|---|")
        for row in store.symbols_for_file_full(page.page_id):
            lines.append(f"| `{row[1]}` | {row[8]}-{row[9]} | `{row[4]}` |")
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ eviction

def recency_of(entry: WorkingSetEntry) -> float:
    """1 / (1 + hours since last access)."""
    try:
        last = datetime.fromisoformat(entry.last_access_at)
    except ValueError:
        return 0.0
    hours = max(0.0, (datetime.now(timezone.utc) - last).total_seconds() / 3600)
    return 1.0 / (1.0 + hours)


def locality_of(store: Store, page: Page, anchor_line: int | None) -> float:
    """Layered locality (plan P1-2) against the global anchor.

    EN: same-file function pages decay with line distance; file pages in the
    same file are constant 1.0; cross-file pages tier by call/file relation.
    ZH: 同文件 function 页按行距衰减；同文件 file 页恒 1.0；跨文件页按
    调用/文件关系分层。
    """
    if anchor_line is None:
        anchor_line = _parse_anchor(store)[1]
        if anchor_line is None:
            # EN: no anchor ever set — treat everything as equally local.
            # ZH: 从未设置锚点 —— 视为同等局部性。
            return LOCALITY_UNRELATED
    if page.granularity == "file":
        # EN: file pages: same file as anchor -> 1.0; otherwise relation tiers.
        # ZH: file 页：与锚点同文件 -> 1.0；否则按关系分层。
        anchor_file = _parse_anchor(store)[0]
        return 1.0 if anchor_file == page.file else LOCALITY_RELATED if page.related_files else LOCALITY_UNRELATED
    anchor_file = _parse_anchor(store)[0]
    if anchor_file == page.file:
        return 1.0 - min(abs(page.line - anchor_line) / LOCALITY_WINDOW, 1.0)
    if page.related_files:
        return LOCALITY_RELATED
    return LOCALITY_UNRELATED


def _parse_anchor(store: Store) -> tuple[str | None, int | None]:
    """Read meta['last_anchor'] as (file, line)."""
    raw = store.get_meta("last_anchor")
    if not raw or ":" not in raw:
        return None, None
    file_part, _, line_part = raw.rpartition(":")
    try:
        return file_part or None, int(line_part)
    except ValueError:
        return None, None


def evict(
    store: Store,
    need_tokens: int,
    *,
    session_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
) -> tuple[list[str], int]:
    """Evict cold pages to free at least need_tokens; returns (evicted, unsatisfied).

    EN: locality is computed fresh against meta['last_anchor'] (v6: no cached
    anchor per entry). Pinned pages are never evicted. If even evicting every
    unpinned page cannot free need_tokens, the shortfall is returned so the
    CLI can warn (plan P1-6 visibility).
    ZH: 淘汰冷页以释放至少 need_tokens；返回（已淘汰页, 未满足 token）。
    locality 对 meta['last_anchor'] 现算（v6：无每条目缓存锚点）。pinned
    永不淘汰。若所有未 pinned 页都淘汰仍不够，返回缺口供 CLI 警告
    （方案 P1-6 可见性）。
    """
    pages: dict[str, Page] = {}
    entries = entries_for_scope(
        store,
        session_id=session_id,
        plan_id=plan_id,
        batch_id=batch_id,
    )
    plan: list[tuple[str, float, float, bool, str, int]] = []
    for entry in entries:
        page = _build_page(store, entry.page_id, None, False)
        if page is None:
            # gone page: evictable at maximum coldness
            plan.append((entry.page_id, 0.0, 0.0, entry.pinned, entry.origin, entry.tokens))
            continue
        pages[entry.page_id] = page
        plan.append(
            (
                entry.page_id,
                recency_of(entry),
                locality_of(store, page, None),
                entry.pinned,
                entry.origin,
                entry.tokens,
            )
        )

    order = budget.suggest_evictions(plan, need_tokens)
    evicted: list[str] = []
    freed = 0
    for page_id in order:
        entry = next((item for item in entries if item.page_id == page_id), None)
        if entry is None:
            continue
        store.delete_working_set_entry(
            page_id,
            session_id=entry.session_id,
            plan_id=entry.plan_id,
            batch_id=entry.batch_id,
        )
        evicted.append(page_id)
        freed += entry.tokens
        if freed >= need_tokens:
            break
    unsatisfied = max(0, need_tokens - freed)
    if evicted:
        store.add_evict_count(len(evicted))
    return evicted, unsatisfied


def ensure_budget(
    store: Store,
    *,
    session_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
) -> tuple[list[str], int]:
    """Enforce working_set/max_pages budgets before inserting a new page.

    EN: returns (evicted, unsatisfied_tokens) — caller warns when the
    shortfall is non-zero. Also flags when a single round evicted >40% of
    max_pages (parameter advice, plan P1-6).
    ZH: 返回（已淘汰页, 未满足 token）—— 缺口非零时调用方警告。单轮淘汰
    超过 max_pages 的 40% 时给出调参建议（方案 P1-6）。
    """
    b = load_budget(store)
    entries = entries_for_scope(
        store,
        session_id=session_id,
        plan_id=plan_id,
        batch_id=batch_id,
    )
    total_tokens = sum(e.tokens for e in entries)
    need = max(0, total_tokens - b.working_set)
    over_pages = max(0, len(entries) - b.max_pages)
    if need <= 0 and over_pages <= 0:
        return [], 0
    # EN: evict for tokens first, then trim pages by coldness.
    # ZH: 先按 token 淘汰，再按冷度裁页。
    evicted, unsatisfied = evict(
        store,
        need,
        session_id=session_id,
        plan_id=plan_id,
        batch_id=batch_id,
    )
    entries = entries_for_scope(
        store,
        session_id=session_id,
        plan_id=plan_id,
        batch_id=batch_id,
    )
    if len(entries) > b.max_pages:
        plan: list[tuple[str, float, float, bool, str, int]] = []
        for entry in entries:
            page = _build_page(store, entry.page_id, None, False)
            loc = locality_of(store, page, None) if page else 0.0
            plan.append((entry.page_id, recency_of(entry), loc, entry.pinned, entry.origin, entry.tokens))
        order = budget.suggest_evictions(plan, 0)
        for page_id in order[: len(entries) - b.max_pages]:
            entry = next((item for item in entries if item.page_id == page_id), None)
            if entry is None:
                continue
            store.delete_working_set_entry(
                page_id,
                session_id=entry.session_id,
                plan_id=entry.plan_id,
                batch_id=entry.batch_id,
            )
            evicted.append(page_id)
    return evicted, unsatisfied


# ------------------------------------------------------------ status / stale

@dataclass
class PageStatus:
    """One working-set row for the status table."""

    page_id: str
    granularity: str
    tokens: int
    last_access_at: str
    pinned: bool
    origin: str
    state: str  # fresh | stale | gone
    # EN: loaded@N vs current index version comparison (plan v6); 0 when the
    # page row is missing (gone).
    # ZH: loaded@N vs current 索引版本对照（方案 v6）；页面行缺失（gone）
    # 时为 0。
    loaded_index_version: int = 0
    current_index_version: int = 0
    session_id: str = ""
    plan_id: str = ""
    batch_id: str = ""


def status(
    store: Store,
    *,
    session_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
) -> list[PageStatus]:
    """Working-set status with stale/gone split (plan v3)."""
    out: list[PageStatus] = []
    for entry in entries_for_scope(
        store,
        session_id=session_id,
        plan_id=plan_id,
        batch_id=batch_id,
    ):
        row = store.symbol_row(entry.page_id) if not _is_file_page(entry.page_id) else None
        if row is not None:
            state = "fresh"
            page_file = row[0]
        elif _is_file_page(entry.page_id):
            frow = store.conn.execute(
                "SELECT hash FROM files WHERE path = ?", (entry.page_id,)
            ).fetchone()
            if frow is None:
                state, page_file = "gone", None
            else:
                state, page_file = "fresh", entry.page_id
        else:
            state, page_file = "gone", None

        page_row = store.get_page(entry.page_id)
        if state == "fresh" and page_row is not None:
            current = store.get_file_hash(page_row[1])
            if current and current != page_row[2]:
                state = "stale"

        granularity = page_row[3] if page_row else ("file" if _is_file_page(entry.page_id) else "function")
        out.append(
            PageStatus(
                page_id=entry.page_id,
                granularity=granularity,
                tokens=entry.tokens,
                last_access_at=entry.last_access_at,
                pinned=entry.pinned,
                origin=entry.origin,
                state=state,
                loaded_index_version=page_row[6] if page_row else 0,
                current_index_version=store.index_version(),
                session_id=entry.session_id,
                plan_id=entry.plan_id,
                batch_id=entry.batch_id,
            )
        )
    return out


def invalidate_stale(store: Store) -> int:
    """Count pages whose recorded version no longer matches the file hash.

    EN: called after an update. pages.version keeps the hash at load time, so
    staleness is derivable on the fly (status()) — this function only counts
    and never rewrites versions (rewriting would erase the mismatch). Pages
    whose file disappeared are 'gone' and keep their last-known values for
    status comparison. Returns the number of stale pages.
    ZH: update 后调用。pages.version 保存加载时的 hash，stale 可即时推导
    （status()）—— 本函数只统计、不改写版本（改写会抹掉失配）。文件已
    消失的页为 'gone'，保留旧值供对照。返回 stale 页数。
    """
    stale = 0
    for page_id, file, version, _gran, _loaded, _cnt, _iv in store.all_pages():
        current = store.get_file_hash(file)
        if current is None:
            continue  # gone — kept for status comparison
        if current != version:
            stale += 1
    return stale


def render_working_set(store: Store, lang: str = "en") -> str:
    """Merge all resident pages, ordered by last_access desc (plan P2-10).

    EN: output is capped by Budget.total (merged-output protection, v6);
    when the cap cuts content, a truncation note is appended.
    ZH: 按 last_access desc 排序合并输出；受 Budget.total 上限保护（v6），
    截断时附说明。
    """
    entries = sorted(
        store.working_set_entries(), key=lambda e: e.last_access_at, reverse=True
    )
    b = load_budget(store)
    chunks: list[str] = []
    used = 0
    truncated = False
    for entry in entries:
        page = _build_page(store, entry.page_id, None, False)
        if page is None:
            continue
        text = render_page(page, lang)
        cost = budget.estimate_tokens(text)
        if used + cost > b.total and chunks:
            truncated = True
            break
        chunks.append(text)
        used += cost
    header = "# Working set / 工作集\n" if lang == "zh" else "# Working set\n"
    body = "\n---\n".join(chunks)
    if truncated:
        note = (
            f"\n> （输出超过预算 {b.total} tokens，已截断；请先 `context evict`。）"
            if lang == "zh"
            else f"\n> (Output exceeded the {b.total}-token budget and was truncated; run `context evict` first.)"
        )
        body += note
    return header + body
