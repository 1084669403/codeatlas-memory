"""EN: Consistency invariants as pure functions (doctor's foundation).

ZH: 一致性不变量纯函数化（doctor 的地基）。

EN: every check returns list[str] — empty means pass. The CLI doctor command
aggregates them and maps non-empty results to exit 1 (plan P2-12). Existing
tests refactored to call these functions instead of private copies.
ZH: 每个检查返回 list[str] —— 空列表即通过。CLI doctor 汇总它们，非空
结果映射为 exit 1（方案 P2-12）。既有测试重构为调用这些函数。
"""

from __future__ import annotations

from pathlib import Path

from .callgraph import check_callgraph_health
from .storage import Store


def check_disk_symbols(store: Store, root: Path) -> list[str]:
    """INV1: every symbol's file exists on disk; no orphan symbol rows."""
    problems: list[str] = []
    for (fpath,) in store.conn.execute("SELECT DISTINCT file FROM symbols"):
        if not (root / fpath).exists():
            problems.append(f"orphan symbols for missing file: {fpath}")
    return problems


def check_fts_sync(store: Store) -> list[str]:
    """INV2: FTS row count matches symbols row count (when FTS enabled)."""
    if not store.fts_enabled:
        return []
    n_sym = store.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    n_fts = store.conn.execute("SELECT COUNT(*) FROM symbols_fts").fetchone()[0]
    if n_sym != n_fts:
        return [f"FTS desync: symbols={n_sym} fts={n_fts}"]
    return []


def check_refs_dangling(store: Store) -> list[str]:
    """INV3: refs edges always point to known files on both ends."""
    known = store.known_paths()
    problems: list[str] = []
    for src, dst, _sym, _cnt in store.all_refs():
        if src not in known:
            problems.append(f"dangling ref src: {src}")
        if dst not in known:
            problems.append(f"dangling ref dst: {dst}")
    return problems


def check_history_on_update(store: Store, history_dir: Path) -> list[str]:
    """INV4: any update that produced changes has a history doc."""
    if not list(history_dir.glob("*.md")):
        return ["update with changes must write a history doc"]
    return []


def check_callgraph(store: Store) -> list[str]:
    """INV5: call-graph resolution rate + raw_calls orphan files (plan v5)."""
    _rate, problems = check_callgraph_health(store)
    return problems


def check_working_set(store: Store) -> list[str]:
    """INV6: no working-set rows whose page no longer exists (orphans).

    EN: a working-set row is an orphan when neither a symbol nor a file
    backing its page_id remains AND the page was never marked gone. For v1
    we treat 'symbol and file both absent' as orphan (plan v5 doctor #6).
    ZH: 当符号与文件都不存在时，工作集行为孤儿行（方案 v5 doctor 第 6 条）。
    """
    problems: list[str] = []
    for entry in store.working_set_entries():
        row = store.symbol_row(entry.page_id)
        if row is not None:
            continue
        frow = store.conn.execute(
            "SELECT path FROM files WHERE path = ?", (entry.page_id,)
        ).fetchone()
        if frow is None:
            problems.append(f"working-set orphan row: {entry.page_id}")
    return problems


def run_all_checks(store: Store, root: Path, history_dir: Path | None = None) -> list[str]:
    """Aggregate every invariant; returns the combined problem list."""
    problems: list[str] = []
    problems.extend(check_disk_symbols(store, root))
    problems.extend(check_fts_sync(store))
    problems.extend(check_refs_dangling(store))
    if history_dir is not None and history_dir.is_dir():
        problems.extend(check_history_on_update(store, history_dir))
    problems.extend(check_callgraph(store))
    problems.extend(check_working_set(store))
    return problems
