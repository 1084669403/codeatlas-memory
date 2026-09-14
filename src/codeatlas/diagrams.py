"""EN: Mermaid diagram generation (directory tree, module dependency, class
inheritance) with strict label sanitization.

ZH: Mermaid 图生成（目录树 / 模块依赖 / 类继承），含严格标签净化。

EN: Sanitization is mandatory — Mermaid renders on GitHub/IDEs and breaks on
'()', ':', quotes and markdown-list-like lines. All user-derived text passes
through _clean() before entering any diagram.
ZH: 净化是强制的 —— Mermaid 在 GitHub/IDE 渲染，'()'、':'、引号与
markdown 列表样式行都会导致渲染失败。所有来自代码的文本进入图前
必须经过 _clean()。
"""

from __future__ import annotations

import re

from .storage import Store

# EN: characters that break Mermaid node labels inside quotes/brackets.
# ZH: 在引号/括号内会破坏 Mermaid 节点标签的字符。
_BAD_CHARS_RE = re.compile(r'["`\(\)\[\]\{\}:;,]')
# EN: markdown list prefixes are rejected by Mermaid ("Unsupported markdown: list").
# ZH: Mermaid 拒绝 markdown 列表前缀（"Unsupported markdown: list"）。
_LIST_PREFIX_RE = re.compile(r"^\s*([-*+]|\d+\.)\s+")


def _clean(text: str, max_len: int = 48) -> str:
    """Sanitize a label for safe embedding in any Mermaid diagram."""
    text = _BAD_CHARS_RE.sub(" ", str(text))
    text = _LIST_PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text or "item"


def _node_id(prefix: str, key: str) -> str:
    """Stable Mermaid node id from a key (path/qname)."""
    import hashlib

    digest = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r"[^A-Za-z0-9_]", "_", key)[-20:]
    return f"{prefix}_{safe}_{digest}"


def directory_tree(paths: list[str]) -> str:
    """Render the project's directory structure as a Mermaid graph.

    EN: directories are intermediate nodes; files are leaves. IDs are derived
    from paths so output is stable across runs (good for diff review).
    ZH: 目录为中间节点，文件为叶子。节点 ID 由路径派生，输出跨次运行
    稳定（利于 diff 审阅）。
    """
    root_id = _node_id("d", "__root__")
    lines = ["graph TD", f'    {root_id}["/"]']
    emitted_dirs: set[str] = set()
    emitted_edges: set[tuple[str, str]] = set()

    for path in sorted(paths):
        parts = path.split("/")
        prev_id = root_id
        # EN: directory chain above the file leaf.
        # ZH: 文件叶子之上的目录链。
        for depth in range(len(parts) - 1):
            dpath = "/".join(parts[: depth + 1])
            if dpath not in emitted_dirs:
                emitted_dirs.add(dpath)
                name = _clean(dpath.rsplit("/", 1)[-1], 32)
                lines.append(f'    {_node_id("d", dpath)}["{name}"]')
            cur_id = _node_id("d", dpath)
            # EN: dedupe edges — many files share the same directory chain.
            # ZH: 边去重 —— 多个文件共享同一条目录链。
            if cur_id != prev_id and (prev_id, cur_id) not in emitted_edges:
                emitted_edges.add((prev_id, cur_id))
                lines.append(f"    {prev_id} --> {cur_id}")
            prev_id = cur_id
        fid = _node_id("f", path)
        lines.append(f'    {fid}["{_clean(parts[-1], 32)}"]')
        lines.append(f"    {prev_id} --> {fid}")
    return "\n".join(lines)


def dependency_graph(edges: list[tuple[str, str, int]], nodes: list[str]) -> str:
    """Render module dependency flowchart from refs edges.

    EN: edge src --> dst labeled with reference count; label capped to keep
    the diagram readable for large projects.
    ZH: 边 src --> dst 带引用次数标签；标签设上限保证大项目可读性。
    """
    lines = ["flowchart LR"]
    node_set = set(nodes)
    emitted: set[str] = set()
    shown = 0
    max_edges = 60  # EN: readability cap / ZH: 可读性上限
    for src, dst, _sym, count in sorted(edges, key=lambda e: (-e[3], e[0], e[1])):
        if shown >= max_edges:
            lines.append(f'    more_{shown}["… {max_edges}+ edges (see .codeatlas/state.db)"]')
            break
        for path in (src, dst):
            if path in node_set and path not in emitted:
                emitted.add(path)
                short = _clean(path.rsplit("/", 1)[-1], 32)
                lines.append(f'    {_node_id("m", path)}["{short}"]')
        if src in node_set and dst in node_set:
            lines.append(f'    {_node_id("m", src)} -->|"{_clean(str(count), 8)}"| {_node_id("m", dst)}')
            shown += 1
    if not emitted:
        lines.append('    empty["no internal dependencies"]')
    return "\n".join(lines)


def inheritance_graph(classes: list[tuple[str, str, list[str]]]) -> str:
    """Render class inheritance as a Mermaid classDiagram.

    EN: classes: (qualified_name, display, bases). Only edges whose base name
    matches a known class get Extension arrows; unknown bases become notes.
    ZH: classes: (限定名, 显示名, 基类)。基类能匹配到已知类的画 Extension
    箭头；未知基类以注释标注。
    """
    if not classes:
        return "classDiagram\n    class EmptyProject"
    lines = ["classDiagram"]
    known: dict[str, str] = {}
    for qname, display, _bases in classes:
        known[display] = _node_id("c", qname)
    seen_edges: set[tuple[str, str]] = set()
    for qname, display, bases in classes:
        cid = _node_id("c", qname)
        lines.append(f"    class {cid} {{")
        lines.append(f"        {_clean(display, 40)}")
        lines.append("    }")
        for base in bases:
            base_clean = _clean(base, 40)
            if base_clean in known:
                key = (known[base_clean], cid)
                if key not in seen_edges:
                    seen_edges.add(key)
                    lines.append(f"    {known[base_clean]} <|-- {cid}")
            else:
                lines.append(f"    note for {cid} \"extends {_clean(base, 30)}\"")
    return "\n".join(lines)


def build_all_diagrams(store: Store) -> dict[str, str]:
    """Convenience: build all three diagrams from the current store state."""
    import json

    file_rows = store.conn.execute("SELECT path FROM files ORDER BY path").fetchall()
    paths = [r[0] for r in file_rows]

    ref_rows = store.all_refs()
    class_rows = store.conn.execute(
        "SELECT qualified_name, name, bases FROM symbols "
        "WHERE kind IN ('class', 'interface') ORDER BY qualified_name"
    ).fetchall()
    classes = [(r[0], r[1], json.loads(r[2])) for r in class_rows]

    return {
        "tree": directory_tree(paths),
        "deps": dependency_graph(ref_rows, paths),
        "inherit": inheritance_graph(classes),
    }
