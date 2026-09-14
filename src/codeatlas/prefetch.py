"""EN: Prefetch neighbours of a loaded page (callers > callees > directory).

ZH: 预取已加载页的邻居（callers > callees > 同目录）。

EN: Prefetch goes through the full budget path (load_page origin="prefetch")
so prefetch pages carry the recency discount at eviction time. Hard caps:
depth-1 only for v1, max_pages per run, stop when the working-set budget is
exhausted (plan P1-5).
ZH: 预取走完整预算路径（load_page origin="prefetch"），淘汰时享受 recency
折扣。硬上限：v1 仅 depth 1、单次 max_pages、工作集预算耗尽即停
（方案 P1-5）。
"""

from __future__ import annotations

from . import budget
from .memory import (
    AmbiguousSymbol,
    Page,
    _is_file_page,
    ensure_budget,
    load_budget,
    load_page,
)
from .storage import Store

MAX_DEPTH = 1  # EN: v1 loads one hop only / ZH: v1 仅加载一跳


def _in_degree(store: Store, qname: str) -> int:
    row = store.conn.execute(
        "SELECT COUNT(*) FROM call_edges WHERE dst_qname = ?", (qname,)
    ).fetchone()
    return row[0]


def _same_dir_files(store: Store, file: str) -> list[str]:
    """Files in the same directory (excluding the file itself)."""
    directory = file.rsplit("/", 1)[0] if "/" in file else ""
    rows = store.conn.execute("SELECT path FROM files ORDER BY path").fetchall()
    out = []
    for (path,) in rows:
        if path == file:
            continue
        path_dir = path.rsplit("/", 1)[0] if "/" in path else ""
        if path_dir == directory:
            out.append(path)
    return out


def _refs_neighbors(store: Store, file: str) -> list[str]:
    """ref import edges in and out of the file."""
    related = set()
    for src, dst, _sym, _cnt in store.all_refs():
        if src == file:
            related.add(dst)
        elif dst == file:
            related.add(src)
    return sorted(related)


def neighbors(store: Store, page: Page) -> list[tuple[str, str, int]]:
    """Ordered neighbour candidates: (page_id, granularity, priority).

    EN: function pages: callers > callees > same-dir high-in-degree symbols >
    file-dependency neighbours. File pages: refs in/out edges > same dir
    (plan P1-2).
    ZH: function 页：callers > callees > 同目录高入度符号 > 文件依赖邻居。
    file 页：refs 出入边邻居 > 同目录（方案 P1-2）。
    """
    out: list[tuple[str, str, int]] = []
    seen: set[str] = set()

    if page.granularity == "file":
        for f in _refs_neighbors(store, page.page_id):
            if f not in seen:
                seen.add(f)
                out.append((f, "file", 0))
        for f in _same_dir_files(store, page.page_id):
            if f not in seen:
                seen.add(f)
                out.append((f, "file", 1))
        return out

    for caller in page.callers:
        if caller not in seen:
            seen.add(caller)
            out.append((caller, "function", 0))
    for callee in page.callees:
        if callee not in seen:
            seen.add(callee)
            out.append((callee, "function", 1))

    # same-directory symbols ranked by in-degree (plan: 同目录高入度)
    directory = page.file.rsplit("/", 1)[0] if "/" in page.file else ""
    candidates: list[tuple[int, str]] = []
    for row in store.conn.execute(
        "SELECT qualified_name, file FROM symbols"
    ).fetchall():
        qname, sfile = row
        if qname in seen or sfile == page.file:
            continue
        sdir = sfile.rsplit("/", 1)[0] if "/" in sfile else ""
        if sdir == directory:
            candidates.append((_in_degree(store, qname), qname))
    for degree, qname in sorted(candidates, reverse=True):
        seen.add(qname)
        out.append((qname, "function", 2))

    # file-dependency neighbours last (related files' file pages)
    for f in page.related_files:
        if f not in seen:
            seen.add(f)
            out.append((f, "file", 3))
    return out


def prefetch(
    store: Store, page: Page, depth: int = 1, max_pages: int = 10
) -> list[str]:
    """Prefetch neighbours; returns the page_ids actually loaded.

    EN: respects the working-set budget (via ensure_budget) and stops at
    max_pages or when candidates run out. Ambiguous bare names are skipped
    silently (prefetch never raises for ambiguity).
    ZH: 遵守工作集预算（经 ensure_budget），达到 max_pages 或候选耗尽即停。
    裸名歧义静默跳过（预取不因歧义抛错）。
    """
    depth = min(depth, MAX_DEPTH)
    b = load_budget(store)
    entries = store.working_set_entries()
    loaded: list[str] = []

    if len(entries) >= b.max_pages:
        return loaded

    candidates = neighbors(store, page)
    for candidate_id, granularity, _prio in candidates:
        if len(loaded) >= max_pages or len(loaded) >= depth * max_pages:
            break
        if len(store.working_set_entries()) >= b.max_pages:
            break
        try:
            got = load_page(store, candidate_id, granularity, origin="prefetch")
        except AmbiguousSymbol:
            continue
        if got is not None:
            loaded.append(got.page_id)
            # EN: keep the working set inside its budget as we go.
            # ZH: 预取过程中保持工作集在预算内。
            ensure_budget(store)
    return loaded
