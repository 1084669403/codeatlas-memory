"""EN: Markdown rendering tests: layering, budget pruning, history links, CJK tokens.
ZH: Markdown 渲染测试：分层、预算裁剪、历史链接、CJK token 估算。
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.indexer import run_scan, run_update
from codeatlas.markdown import estimate_tokens, render_detail_files, render_overview
from codeatlas.storage import Store


def _scan(tmp_path: Path) -> Store:
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store, output_lang="en")
    return store


def test_overview_structure(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(): pass", encoding="utf-8")
    store = _scan(tmp_path)
    out = tmp_path / "CODEATLAS.md"
    render_overview(tmp_path, store, run_scan(tmp_path, store), out, lang="en")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("---\n")  # frontmatter
    assert text.count("```mermaid") == 4  # tree + deps + inherit + call graph
    assert "## Files" in text
    assert "`a.py`" in text
    assert "codeatlas scan ." in text  # regenerate hint for teammates
    store.close()


def test_detail_shards_written(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f(): pass", encoding="utf-8")
    (tmp_path / "b.py").write_text("def g(): pass", encoding="utf-8")
    store = _scan(tmp_path)
    detail = tmp_path / ".codeatlas" / "detail"
    counts = render_detail_files(store, detail, "en")
    files = list(detail.glob("*.md"))
    assert len(files) == 2  # src/ and (root)
    assert counts["src"] == 1
    text = files[0].read_text(encoding="utf-8")
    assert "signature:" in text
    assert "entries)" in text  # header states entry count
    store.close()


def test_budget_pruning_marks_omitted(tmp_path: Path) -> None:
    for i in range(6):
        (tmp_path / f"f{i}.py").write_text(f"def fn{i}(): pass", encoding="utf-8")
    store = _scan(tmp_path)
    out = tmp_path / "CODEATLAS.md"
    render_overview(tmp_path, store, run_scan(tmp_path, store), out, lang="en", max_tokens=420)
    text = out.read_text(encoding="utf-8")
    assert "omitted" in text
    assert "`f0.py`" in text or "`f5.py`" in text
    store.close()


def test_cjk_token_estimator() -> None:
    # EN: 4 CJK chars ~4 tokens (NOT 4/4*0.25); 33 ascii chars ~11 tokens.
    # ZH: 4 个汉字约 4 token（而非 len/4）；33 个 ASCII 字符约 11 token。
    assert estimate_tokens("打印消息") == 4
    assert 9 <= estimate_tokens("a" * 33) <= 12
    assert estimate_tokens("") == 0


def test_recent_history_links(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(): pass", encoding="utf-8")
    store = _scan(tmp_path)
    hist = tmp_path / ".codeatlas" / "history"
    hist.mkdir(parents=True)
    (hist / "2026-09-14_1200.md").write_text("# x", encoding="utf-8")
    out = tmp_path / "CODEATLAS.md"
    render_overview(tmp_path, store, run_scan(tmp_path, store), out, lang="en")
    text = out.read_text(encoding="utf-8")
    assert "## Recent Changes" in text
    assert ".codeatlas/history/2026-09-14_1200.md" in text
    store.close()
