"""EN: Call-graph construction in two stages.

ZH: 调用图构建（两阶段）。

EN: Stage A (parser.py) collects raw call edges per file into the raw_calls
table. Stage B (this module) resolves callee_raw text against known symbols
and rewrites the call_edges table. Resolution is heuristic and approximate:
decorator calls, dynamic dispatch and higher-order callbacks are known
limitations (documented in README).
ZH: 阶段 A（parser.py）把每个文件的原始调用边写入 raw_calls 表。
阶段 B（本模块）将 callee_raw 文本对已知符号做解析并重写 call_edges 表。
解析是启发式近似的：装饰器调用、动态分派、高阶回调为已知限制
（README 已注明）。
"""

from __future__ import annotations

from .storage import Store


def _load_symbol_maps(store: Store) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Build lookup maps: bare name -> qname(s), and qname -> file."""
    bare: dict[str, list[str]] = {}
    qnames: dict[str, str] = {}
    for row in store.conn.execute(
        "SELECT qualified_name, name, file FROM symbols"
    ).fetchall():
        qname, name, file = row
        qnames[qname] = file
        bare.setdefault(name, []).append(qname)
    return qnames, bare


def _load_import_map(store: Store) -> dict[str, dict[str, str]]:
    """Map per-file imported names to the defining file's module prefix.

    EN: from the refs table (src_file -> dst_file, symbol = imported name) we
    know which file a name was imported from; the symbol's module prefix is
    derived from the dst file path (dotted for Python).
    ZH: 从 refs 表（src_file -> dst_file，symbol = 导入名）可知名字来自哪个
    文件；定义文件路径推出其模块前缀（Python 用点分）。
    """
    imap: dict[str, dict[str, str]] = {}
    for src, dst, symbol, _cnt in store.all_refs():
        prefix = _module_prefix(dst)
        if prefix:
            imap.setdefault(src, {})[symbol] = prefix
    return imap


def _module_prefix(dst_file: str) -> str:
    """Derive a module prefix from a file path (codeatlas/parser.py -> codeatlas.parser)."""
    p = dst_file
    if p.endswith("/__init__.py"):
        p = p[: -len("/__init__.py")]
    elif p.endswith(".py"):
        p = p[: -len(".py")]
    elif p.endswith((".tsx", ".ts", ".jsx", ".mjs", ".cjs", ".js")):
        for ext in (".tsx", ".ts", ".jsx", ".mjs", ".cjs", ".js"):
            if p.endswith(ext):
                p = p[: -len(ext)]
                break
    return p.replace("/", ".")


def resolve_callee(
    src_qname: str,
    callee_raw: str,
    src_file: str,
    qnames: dict[str, str],
    bare: dict[str, list[str]],
    import_map: dict[str, dict[str, str]],
) -> str | None:
    """Resolve one raw callee to a qualified name, or None (unresolved).

    EN: resolution order (Python plan): bare name (same file first) ->
    same-class method (self.x) -> from-import mapping -> give up.
    ZH: 解析顺序（方案）：裸名（同文件优先）-> 同类方法（self.x）->
    from-import 映射 -> 放弃。
    """
    # 1) same-class method: self.x / cls.x -> look inside the caller's class
    if callee_raw.startswith(("self.", "cls.")):
        method = callee_raw.split(".", 1)[1]
        # caller qname like "pkg.mod.Class.method"; try the enclosing class prefix
        prefix = src_qname.rsplit(".", 1)[0]
        candidate = f"{prefix}.{method}"
        if candidate in qnames:
            return candidate
        # one more level up (caller itself is a class -> nested case is out of scope)
        return None

    # attribute chains like obj.method: try the final segment only when the
    # object is the module itself is NOT attempted (module-level pages are out
    # of scope); otherwise unresolved.
    if "." in callee_raw:
        # e.g. "module.func" where module is an imported name
        first, rest = callee_raw.split(".", 1)
        prefix = import_map.get(src_file, {}).get(first)
        if prefix:
            candidate = f"{prefix}.{rest}"
            if candidate in qnames:
                return candidate
        # last resort: match by trailing segment against known qnames
        candidates = bare.get(rest, [])
        if len(candidates) == 1:
            return candidates[0]
        if candidates:
            # prefer same-file
            for c in candidates:
                if qnames.get(c) == src_file:
                    return c
        return None

    # 2) bare name: same-file function/method first, then unique global
    candidates = bare.get(callee_raw, [])
    if len(candidates) == 1:
        return candidates[0]
    same_file = [c for c in candidates if qnames.get(c) == src_file]
    if len(same_file) == 1:
        return same_file[0]
    if candidates:
        # ambiguous bare name -> unresolved (documented limitation)
        return None
    # 3) from-import mapping: name imported from another module
    prefix = import_map.get(src_file, {}).get(callee_raw)
    if prefix:
        candidate = f"{prefix}.{callee_raw}"
        if candidate in qnames:
            return candidate
    return None


def rebuild_call_edges(store: Store) -> float:
    """Stage B: resolve all raw_calls -> rewrite call_edges table.

    Returns the resolution rate (resolved / total raw calls) for doctor
    reporting; the rate is also stored in meta.
    """
    qnames, bare = _load_symbol_maps(store)
    import_map = _load_import_map(store)

    file_of: dict[str, str] = {}
    # src_qname may appear in several files only in pathological cases; the
    # symbols table is authoritative.
    for row in store.conn.execute("SELECT qualified_name, file FROM symbols"):
        file_of[row[0]] = row[1]

    resolved_edges: dict[tuple[str, str], int] = {}
    total = 0
    resolved = 0
    for _file, src_qname, callee_raw, _line in store.all_raw_calls():
        total += 1
        src_file = file_of.get(src_qname)
        if src_file is None:
            continue  # caller symbol vanished (deleted but raw_calls not yet swept)
        dst = resolve_callee(src_qname, callee_raw, src_file, qnames, bare, import_map)
        if dst is None or dst == src_qname:
            continue
        resolved += 1
        key = (src_qname, dst)
        resolved_edges[key] = resolved_edges.get(key, 0) + 1

    edges = [(s, d, c) for (s, d), c in sorted(resolved_edges.items())]
    store.replace_call_edges(edges)
    rate = (resolved / total) if total else 1.0
    store.set_meta("call_resolution_rate", f"{rate:.4f}")
    store.set_meta("call_resolution_total", str(total))
    return rate


def callers_of(store: Store, qname: str) -> list[str]:
    """Qualified names that call qname (dedup, sorted)."""
    return store.callers_of(qname)


def callees_of(store: Store, qname: str) -> list[str]:
    """Qualified names that qname calls (dedup, sorted)."""
    return store.callees_of(qname)


def check_callgraph_health(store: Store) -> tuple[float, list[str]]:
    """Resolution rate + orphan file detection (used by doctor).

    EN: returns (rate, problems). Orphan raw_calls rows belong to files no
    longer in the index (missed cleanup).
    ZH: 返回（解析率, 问题列表）。raw_calls 中出现索引里已不存在的文件
    即为孤儿（清理遗漏）。
    """
    problems: list[str] = []
    raw_total = store.conn.execute("SELECT COUNT(*) FROM raw_calls").fetchone()[0]
    rate_raw = store.get_meta("call_resolution_rate")
    rate = float(rate_raw) if rate_raw else 1.0
    if raw_total and rate < 0.30:
        problems.append(
            f"call resolution rate low: {rate:.0%} (<30%) — call graph may be unreliable"
        )
    known = store.known_paths()
    orphans = sorted(store.raw_call_files() - known)
    for path in orphans:
        problems.append(f"raw_calls orphan file: {path}")
    return rate, problems
