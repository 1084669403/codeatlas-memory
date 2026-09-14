"""EN: Mermaid diagram tests: sanitization, structure, stability.
ZH: Mermaid 图测试：净化、结构、稳定性。
"""

from __future__ import annotations

from codeatlas.diagrams import _clean, dependency_graph, directory_tree, inheritance_graph


def test_clean_strips_breaking_chars() -> None:
    assert "(" not in _clean("f(x: int)")
    assert ":" not in _clean("a: b")
    assert '"' not in _clean('say "hi"')


def test_clean_strips_list_prefixes() -> None:
    # EN: mermaid rejects markdown-list-like labels (issue #6099).
    # ZH: mermaid 拒绝 markdown 列表样式标签（issue #6099）。
    out = _clean("- item one")
    assert not out.startswith("-")
    out2 = _clean("1. numbered")
    assert not out2.startswith("1.")


def test_clean_truncates_long_labels() -> None:
    out = _clean("x" * 200, max_len=48)
    assert len(out) <= 48


def test_directory_tree_structure() -> None:
    tree = directory_tree(["src/a.py", "src/b/c.ts"])
    assert tree.startswith("graph TD")
    assert tree.count("-->") == 4  # root->src, src->a.py, src->b, b->c.ts
    # stability: same input -> same output (good for diff review)
    assert tree == directory_tree(["src/a.py", "src/b/c.ts"])


def test_dependency_graph_edges() -> None:
    nodes = ["a.py", "b.py"]
    edges = [("a.py", "b.py", "helper", 3)]
    out = dependency_graph(edges, nodes)
    assert out.startswith("flowchart LR")
    assert "-->" in out


def test_dependency_graph_empty() -> None:
    out = dependency_graph([], ["a.py"])
    assert "no internal dependencies" in out


def test_inheritance_known_and_unknown_bases() -> None:
    classes = [
        ("a.Base", "Base", []),
        ("a.Child", "Child", ["Base", "External"]),
    ]
    out = inheritance_graph(classes)
    assert out.startswith("classDiagram")
    assert "<|--" in out  # known base -> extension arrow
    assert "extends External" in out  # unknown base -> note
