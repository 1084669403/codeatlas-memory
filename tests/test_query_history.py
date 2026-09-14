"""EN: Query & history command tests: zh hits, priority order, rename chains.
ZH: query 与 history 命令测试：中文命中、优先级排序、重命名链。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from codeatlas.cli import _search
from codeatlas.indexer import run_scan, run_update
from codeatlas.storage import Store


def _touch(p: Path) -> None:
    st = p.stat()
    os.utime(p, (st.st_atime + 5, st.st_mtime + 5))


def test_query_chinese_hit_fts(tmp_path: Path) -> None:
    (tmp_path / "工具.py").write_text(
        "def 打印消息(text: str) -> None:\n    '''打印文本到控制台'''\n    print(text)\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store, output_lang="zh")
    rows = _search(store, "打印消息", 10)
    assert rows, "Chinese query must hit via trigram FTS"
    assert any("打印消息" in r[2] for r in rows)
    store.close()


def test_query_short_text_like_fallback(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def ab(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    # EN: <3 chars cannot use trigram; LIKE must still find it.
    # ZH: 少于 3 字符无法用 trigram；LIKE 必须仍能命中。
    rows = _search(store, "ab", 10)
    assert any(r[2] == "a.ab" for r in rows)
    store.close()


def test_query_priority_exact_name_first(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def clean(): '''Clean it.'''\n\ndef clean_data(): '''Clean data.'''\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    rows = _search(store, "clean", 10)
    assert rows[0][2] == "a.clean"  # exact name beats prefix match
    store.close()


def test_history_follows_rename_chain(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text("def old_name(a: int) -> int:\n    return a\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    time.sleep(0.02)
    p.write_text("def new_name(a: int) -> int:\n    return a\n", encoding="utf-8")
    _touch(p)
    run_update(tmp_path, store)
    # EN: chain from the NEW name must reach the OLD name's records.
    # ZH: 从新名出发的演变链必须能到达旧名的记录。
    new_records = store.changes_for_symbol("a.new_name")
    assert any(c.change_type.value == "renamed" for c in new_records)
    renamed = next(c for c in new_records if c.change_type.value == "renamed")
    assert renamed.old_value == "a.old_name"
    old_records = store.changes_for_symbol("a.old_name")
    assert any(c.change_type.value == "added" for c in old_records)
    store.close()


def test_history_bare_name_lists_all_qualnames(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def dup(): pass", encoding="utf-8")
    (tmp_path / "b.py").write_text("def dup(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    counts = store.changes_by_symbol_name("dup")
    assert set(counts) == {"a.dup", "b.dup"}
    store.close()
