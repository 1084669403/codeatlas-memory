"""EN: Orchestration for full scan and incremental update, including symbol
diffing and project-internal reference edge counting.

ZH: 全量扫描与增量更新的编排逻辑，包含符号 diff 与项目内引用边统计。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .models import (
    BODY_MAX_BYTES,
    ChangeRecord,
    ChangeType,
    FileRecord,
    ScanResult,
    Symbol,
)
from .callgraph import rebuild_call_edges
from .parser import parse_file
from .scanner import scan_files
from .storage import Store
from .summarizer import RuleSummarizer, enrich


def invalidate_stale(store: Store) -> int:
    """Mark stale/gone pages after an update (implemented in memory.py).

    EN: imported lazily to keep indexer's import graph simple until memory
    exists; memory.py will own the real logic.
    ZH: 惰性导入以保持 indexer 的依赖图简单；真实逻辑由 memory.py 拥有。
    """
    from .memory import invalidate_stale as _invalidate

    return _invalidate(store)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _body_diff_detail(old_body: str, new_body: str) -> str:
    """Render "+N/-M" for two normalized bodies (difflib, stdlib only)."""
    import difflib

    diff = difflib.unified_diff(
        old_body.splitlines(), new_body.splitlines(), lineterm="", n=0
    )
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    return f"+{added}/-{removed}"


def _body_comparable(old_body: str, new_body: str) -> bool:
    """Whether a body-level diff comparison is meaningful.

    EN: migrated baselines carry body='' (pre-v2 rows) — writing the new body
    silently without recording a diff avoids noise (plan P1-1). Truncated
    bodies (64KB cap) also skip the diff.
    ZH: 迁移基线的旧行 body=''（v2 之前的行）—— 静默写入新 body、不记
    diff，避免噪音（方案 P1-1）。被截断的体（64KB 上限）同样跳过 diff。
    """
    if not old_body:
        return False  # migration baseline: silent write
    truncated = (
        len(new_body.encode("utf-8", "replace")) >= BODY_MAX_BYTES
        or len(old_body.encode("utf-8", "replace")) >= BODY_MAX_BYTES
    )
    return not truncated


def diff_file_symbols(
    old_syms: list[tuple], new_record: FileRecord
) -> list[ChangeRecord]:
    """Diff stored symbol tuples vs a freshly parsed FileRecord.

    EN: old_syms rows come from symbols_for_file_full (13 fields incl. body).
    Uses qualified names as diff keys (SCIP-style). Signature-stable symbols
    get SIGNATURE_STABLE only when the normalized body really changed, with
    detail="+N/-M" (plan MVP gap 1).
    ZH: old_syms 行来自 symbols_for_file_full（13 字段，含 body）。
    以限定名为 diff 键（SCIP 风格）。签名未变的符号仅在体真实变化时记
    SIGNATURE_STABLE，detail="+N/-M"（方案 MVP 缺口 1）。
    """
    ts = _now_iso()
    changes: list[ChangeRecord] = []
    old_by_qname = {row[1]: row for row in old_syms}
    new_by_qname = {s.qualified_name: s for s in new_record.symbols}

    for qname, row in old_by_qname.items():
        if qname not in new_by_qname:
            changes.append(
                ChangeRecord(
                    ts=ts,
                    file=new_record.path,
                    symbol=qname,
                    change_type=ChangeType.REMOVED,
                    old_value=row[4],
                    new_value=None,
                )
            )

    for qname, sym in new_by_qname.items():
        if qname not in old_by_qname:
            changes.append(
                ChangeRecord(
                    ts=ts,
                    file=new_record.path,
                    symbol=qname,
                    change_type=ChangeType.ADDED,
                    old_value=None,
                    new_value=sym.signature,
                )
            )
            continue
        _, _, _, _, old_sig, old_params, old_returns, _, _, _, _, _, old_body = old_by_qname[qname]
        if old_sig != sym.signature or old_params != sym.params or old_returns != sym.returns:
            changes.append(
                ChangeRecord(
                    ts=ts,
                    file=new_record.path,
                    symbol=qname,
                    change_type=ChangeType.SIGNATURE_CHANGED,
                    old_value=old_sig,
                    new_value=sym.signature,
                )
            )
        elif _body_comparable(old_body, sym.body) and old_body != sym.body:
            # EN: signature unchanged but body really changed — record with
            # line counts so history shows body-level edits (honest change log).
            # ZH: 签名未变但体真实变化 —— 记录行数，让历史呈现体级修改。
            changes.append(
                ChangeRecord(
                    ts=ts,
                    file=new_record.path,
                    symbol=qname,
                    change_type=ChangeType.SIGNATURE_STABLE,
                    old_value=old_sig,
                    new_value=sym.signature,
                    detail=_body_diff_detail(old_body, sym.body),
                )
            )
    return changes


def _sig_shape(sig: str, name: str) -> str:
    """Signature with the bare name removed — the rename-comparison shape.

    EN: full signature text never matches across a rename because the name is
    embedded in it; stripping the bare name leaves the comparable shape.
    ZH: 完整签名在重命名后必然不同（名字嵌在其中）；去掉裸名后剩下的
    "形状"才是可比部分。
    """
    import re

    if name:
        sig = re.sub(rf"\b{re.escape(name)}\b", "", sig, count=1)
    return " ".join(sig.split())


def detect_renames(changes: list[ChangeRecord]) -> list[ChangeRecord]:
    """Pair same-file added+removed symbols with identical signature shapes.

    EN: In-file add/remove pair whose name-stripped signatures match ->
    suspected rename. Replaces the pair with a single RENAMED record
    (old qname -> new qname).
    ZH: 同文件内"一删一增且去名签名形状相同" -> 疑似重命名；合并为一条
    RENAMED 记录（旧限定名 -> 新限定名），供 history 命令跟链。
    """
    ts = _now_iso()
    removed_by_shape: dict[str, list[ChangeRecord]] = {}
    for ch in changes:
        if ch.change_type == ChangeType.REMOVED and ch.old_value:
            bare = ch.symbol.rsplit(".", 1)[-1]
            shape = _sig_shape(ch.old_value, bare)
            removed_by_shape.setdefault(shape, []).append(ch)

    out: list[ChangeRecord] = []
    consumed: set[int] = set()
    for ch in changes:
        if id(ch) in consumed:
            continue
        if ch.change_type == ChangeType.ADDED and ch.new_value:
            bare = ch.symbol.rsplit(".", 1)[-1]
            candidates = removed_by_shape.get(_sig_shape(ch.new_value, bare), [])
            # EN: same-file constraint prevents cross-file false pairing.
            # ZH: 同文件约束避免跨文件误配对。
            match = next(
                (r for r in candidates if id(r) not in consumed and r.file == ch.file),
                None,
            )
            if match is not None and match.symbol != ch.symbol:
                consumed.add(id(ch))
                consumed.add(id(match))
                out.append(
                    ChangeRecord(
                        ts=ts,
                        file=ch.file,
                        symbol=ch.symbol,
                        change_type=ChangeType.RENAMED,
                        old_value=match.symbol,
                        new_value=ch.symbol,
                    )
                )
                continue
        out.append(ch)
    # drop consumed removals
    return [c for c in out if id(c) not in consumed]


def _resolve_imports(record: FileRecord, all_paths: set[str]) -> list[tuple[str, str, int]]:
    """Resolve a file's imports to project-internal file edges.

    EN: Heuristic resolution:
    - python: dotted module path -> try file.py / package/__init__.py
    - js/ts: relative source './x' -> try x.ts/x.js/x/index.ts/...
    Only project files (from all_paths) are linked; external imports are skipped.
    ZH: 启发式解析：
    - python：点分模块路径 -> 尝试 file.py / 包/__init__.py
    - js/ts：相对导入 './x' -> 尝试 x.ts/x.js/x/index.ts 等
    仅连接项目内文件；外部依赖跳过。
    """
    # EN: (src, dst) -> [count, first_imported_name]
    # ZH: (src, dst) -> [次数, 第一个导入名]
    edges: dict[tuple[str, str], list] = {}
    path_set = all_paths

    for imp in record.imports:
        src = imp.source
        if not src:
            continue
        candidates: list[str] = []
        if record.language == "python":
            if src.startswith("."):
                # EN: Relative import: count leading dots, resolve against the
                # current file's directory. E.g. from .plans import X in
                # src/codeatlas/cli.py -> src/codeatlas/plans.py
                # ZH: 相对导入：计算前导点数，基于当前文件目录解析。
                level = len(src) - len(src.lstrip("."))
                module = src[level:]
                base_dir = Path(record.path).parent.as_posix()
                for _ in range(level - 1):
                    base_dir = Path(base_dir).parent.as_posix()
                if module:
                    base = f"{base_dir}/{module}"
                    candidates = [f"{base}.py", f"{base}/__init__.py"]
                else:
                    candidates = [f"{base_dir}/__init__.py"]
                    # EN: `from . import submodule` should resolve to the
                    # submodule file, not __init__.py, when a matching .py
                    # exists in the same directory.
                    # ZH: `from . import 模块` 应解析到同目录下的模块文件。
                    for name in imp.names:
                        sub_candidate = f"{base_dir}/{name}.py"
                        if sub_candidate in path_set:
                            candidates = [sub_candidate]
                            break
            else:
                base = src.replace(".", "/")
                candidates = [f"{base}.py", f"{base}/__init__.py"]
        else:
            if src.startswith("."):
                base_dir = str(Path(record.path).parent)
                joined = str(Path(base_dir, src))
                norm = Path(joined).as_posix()
                candidates = [
                    f"{norm}.ts", f"{norm}.tsx", f"{norm}.js", f"{norm}.jsx",
                    f"{norm}.mjs", f"{norm}.cjs",
                    f"{norm}/index.ts", f"{norm}/index.tsx", f"{norm}/index.js",
                ]
                # EN: normalize './a/../b' style remnants
                # ZH: 规范化 './a/../b' 类残留
                candidates = [Path(c).as_posix() for c in candidates]
        for cand in candidates:
            if cand in path_set:
                slot = edges.setdefault((record.path, cand), [0, imp.names[0] if imp.names else cand])
                slot[0] += 1
                break

    # EN: one edge per (src,dst); symbol is the first imported name for context.
    # ZH: 每 (src,dst) 一条边；symbol 取第一个导入名做上下文。
    return [(s, d, sym, n) for (s, d), (n, sym) in edges.items()]


def _build_in_degrees(store: Store) -> dict[str, int]:
    """Aggregate incoming reference counts per file (used for budget pruning)."""
    degrees: dict[str, int] = {}
    for src, dst, _sym, count in store.all_refs():
        degrees[dst] = degrees.get(dst, 0) + count
    return degrees


def run_scan(
    root: Path, store: Store, lang: str = "en", output_lang: str = "en"
) -> ScanResult:
    """Full scan: parse every file, rebuild state, record initial additions."""
    ts = _now_iso()
    result = ScanResult(root=str(root), lang=output_lang, timestamp=ts)
    summarizer = RuleSummarizer()

    files = scan_files(root)
    result.files_scanned = len(files)
    all_rel_paths = {f.relative_to(root).as_posix() for f in files}

    parsed_records: list[FileRecord] = []
    for fp in files:
        record = parse_file(root, fp)
        enrich(record, summarizer, output_lang)
        parsed_records.append(record)
        result.symbols_found += len(record.symbols)
    result.files_parsed = len(parsed_records)

    # EN: rebuild state from scratch (scan semantics), then append ADDED history.
    # ZH: 全量重建状态（scan 语义），然后追加 ADDED 历史。
    store.conn.execute("DELETE FROM refs")
    store.conn.execute("DELETE FROM symbols")
    store.conn.execute("DELETE FROM files")
    store.conn.commit()

    changes: list[ChangeRecord] = []
    for record in parsed_records:
        store.upsert_file(record, ts)
        for sym in record.symbols:
            changes.append(
                ChangeRecord(
                    ts=ts,
                    file=record.path,
                    symbol=sym.qualified_name,
                    change_type=ChangeType.ADDED,
                    new_value=sym.signature,
                )
            )
    for record in parsed_records:
        store.replace_raw_calls(record.path, record.calls)
        edges = _resolve_imports(record, all_rel_paths)
        if edges:
            store.replace_refs_for_file(record.path, edges)

    store.append_changes(changes)
    store.set_meta("lang", output_lang)
    store.set_meta("schema_version", str(2))
    store.set_meta("last_scan", ts)
    # EN: full rebuild invalidates the working set (pages stats stay) and
    # rewrites the call graph from the fresh raw_calls.
    # ZH: 全量重建使工作集失效（pages 统计保留），并用新 raw_calls 重写调用图。
    store.clear_working_set()
    rebuild_call_edges(store)
    store.bump_index_version()
    store.reset_evict_count()
    result.changes = changes
    return result


def run_update(
    root: Path, store: Store, output_lang: str = "en"
) -> ScanResult:
    """Incremental update: re-parse only changed files, diff symbols, log changes.

    EN: Falls back to a full scan when the store is empty (no state.db yet).
    If the stored output language differs, a full re-scan keeps descriptions
    consistent (documented v3 decision).
    ZH: 状态库为空时自动退化为全量 scan；输出语言变更时全量重扫，
    保证描述语言一致（v3 既定决策）。
    """
    stored_lang = store.get_meta("lang")
    known = store.known_paths()
    if not known or (stored_lang is not None and stored_lang != output_lang):
        result = run_scan(root, store, output_lang=output_lang)
        if stored_lang is not None and stored_lang != output_lang:
            # EN: language switch surfaced to caller for a friendly notice.
            # ZH: 语言切换信息返回给调用方用于提示。
            result.files_skipped = -1  # sentinel: language switched
        return result

    ts = _now_iso()
    result = ScanResult(root=str(root), lang=output_lang, timestamp=ts)
    summarizer = RuleSummarizer()

    files = scan_files(root)
    result.files_scanned = len(files)
    all_rel_paths = {f.relative_to(root).as_posix() for f in files}

    changed_records: list[FileRecord] = []
    deleted_paths: list[str] = []

    # EN: two-stage quick path per file.
    # ZH: 每个文件走两段式快速路径。
    for fp in files:
        rel = fp.relative_to(root).as_posix()
        stat_size = fp.stat().st_size
        row = store.conn.execute(
            "SELECT mtime, size FROM files WHERE path = ?", (rel,)
        ).fetchone()
        if row is not None and row[1] == stat_size and abs(fp.stat().st_mtime - row[0]) < 1e-6:
            result.files_skipped += 1
            continue
        record = parse_file(root, fp)
        if row is not None and store.get_file_hash(rel) == record.hash:
            # mtime changed but content identical (git checkout): update metadata only
            store.conn.execute(
                "UPDATE files SET mtime = ?, size = ? WHERE path = ?",
                (record.mtime, record.size, rel),
            )
            result.files_skipped += 1
            continue
        enrich(record, summarizer, output_lang)
        changed_records.append(record)

    stored_paths = known
    deleted_paths = sorted(stored_paths - all_rel_paths)

    changes: list[ChangeRecord] = []
    for path in deleted_paths:
        old_syms = store.symbols_for_file(path)
        for row in old_syms:
            changes.append(
                ChangeRecord(
                    ts=ts,
                    file=path,
                    symbol=row[1],
                    change_type=ChangeType.REMOVED,
                    old_value=row[4],
                )
            )
        store.delete_file(path)
        store.conn.execute("DELETE FROM refs WHERE src_file = ? OR dst_file = ?", (path, path))
        # EN: sweep raw calls of deleted files — prevents orphan accumulation
        # and keeps call_edges rebuild clean (plan v5).
        # ZH: 清理被删文件的 raw calls —— 防孤儿累积，保持 call_edges
        # 重算干净（方案 v5）。
        store.delete_raw_calls(path)

    for record in changed_records:
        old_syms = store.symbols_for_file_full(record.path)
        file_changes = diff_file_symbols(old_syms, record)
        # EN: only log body-level counts for signature-stable symbols via detail.
        # ZH: 对签名未变的符号在 detail 中记录体级变化行数。
        store.upsert_file(record, ts)
        changes.extend(file_changes)
        store.replace_raw_calls(record.path, record.calls)
        edges = _resolve_imports(record, all_rel_paths)
        store.replace_refs_for_file(record.path, edges)
        result.symbols_found += len(record.symbols)

    # EN: removed files may have been the only referencer of some edges; recompute
    # in-degrees lazily on read rather than eagerly (refs table is the source of truth).
    # ZH: 被删文件可能是某些边的唯一引用方；入度在读取时惰性聚合
    # （refs 表即真相源）。
    changes = detect_renames(changes)
    store.append_changes(changes)
    store.set_meta("last_update", ts)
    # EN: call graph rewrite from the persisted raw_calls (P0-2: unchanged
    # files keep their raw calls, so a full rebuild is safe and cheap), then
    # staleness invalidation and version bump.
    # ZH: 基于持久化的 raw_calls 重写调用图（P0-2：未变更文件的 raw calls
    # 保留，全量重算安全且廉价），随后失效处理与版本递增。
    rebuild_call_edges(store)
    invalidated = invalidate_stale(store)
    store.bump_index_version()
    store.reset_evict_count()
    result.changes = changes
    result.files_parsed = len(changed_records)
    return result


def in_degrees(store: Store) -> dict[str, int]:
    """Public accessor for per-file in-degree (used by markdown budget pruning)."""
    return _build_in_degrees(store)
