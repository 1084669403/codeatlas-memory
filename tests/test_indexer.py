"""EN: Incremental update tests: skip-unchanged, diff correctness, renames, lang switch.
ZH: 增量更新测试：跳过未变文件、diff 正确性、重命名检测、语言切换。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from codeatlas.indexer import run_scan, run_update
from codeatlas.models import ChangeType
from codeatlas.storage import Store


def _touch(path: Path) -> None:
    # EN: ensure mtime actually changes on coarse-grained filesystems.
    # ZH: 粗粒度时间戳的文件系统上确保 mtime 真正变化。
    st = path.stat()
    os.utime(path, (st.st_atime + 5, st.st_mtime + 5))


def test_scan_then_noop_update(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    r = run_update(tmp_path, store)
    assert r.files_parsed == 0
    assert r.changes == []
    store.close()


def test_mtime_only_change_skipped(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text("def f(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    time.sleep(0.02)
    _touch(p)  # same content, new mtime
    r = run_update(tmp_path, store)
    assert r.files_parsed == 0  # two-stage fast path: hash identical
    store.close()


def test_signature_change_and_addition(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text("def f(a: int) -> int:\n    '''Doc.'''\n    return a\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)

    time.sleep(0.02)
    p.write_text(
        "def f(a: int, b: int = 0) -> int:\n    '''Doc.'''\n    return a + b\n\n\ndef g() -> str:\n    return 'x'\n",
        encoding="utf-8",
    )
    _touch(p)
    r = run_update(tmp_path, store)
    types = {c.symbol: c.change_type for c in r.changes}
    assert types["a.f"] == ChangeType.SIGNATURE_CHANGED
    assert types["a.g"] == ChangeType.ADDED
    ch = next(c for c in r.changes if c.symbol == "a.f")
    assert ch.old_value == "def f(a: int) -> int"
    assert ch.new_value == "def f(a: int, b: int = 0) -> int"
    store.close()


def test_body_change_is_signature_stable(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text("def f() -> str:\n    return 'v1'\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    time.sleep(0.02)
    p.write_text("def f() -> str:\n    return 'v2-changed'\n", encoding="utf-8")
    _touch(p)
    r = run_update(tmp_path, store)
    assert r.changes[0].change_type == ChangeType.SIGNATURE_STABLE
    store.close()


def test_rename_detection(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text("def old_name(a: int) -> int:\n    return a\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    time.sleep(0.02)
    p.write_text("def new_name(a: int) -> int:\n    return a\n", encoding="utf-8")
    _touch(p)
    r = run_update(tmp_path, store)
    renamed = [c for c in r.changes if c.change_type == ChangeType.RENAMED]
    assert len(renamed) == 1
    assert renamed[0].old_value == "a.old_name"
    assert renamed[0].new_value == "a.new_name"
    store.close()


def test_file_deletion_logged(tmp_path: Path) -> None:
    p = tmp_path / "a.py"
    p.write_text("def f(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    time.sleep(0.02)
    p.unlink()
    r = run_update(tmp_path, store)
    assert any(c.change_type == ChangeType.REMOVED for c in r.changes)
    assert store.known_paths() == set()
    store.close()


def test_lang_switch_triggers_full_rescan(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store, output_lang="en")
    r = run_update(tmp_path, store, output_lang="zh")
    assert r.files_skipped == -1  # sentinel: language switched
    assert store.get_meta("lang") == "zh"
    store.close()


def test_refs_edges_built(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def provider(): pass", encoding="utf-8")
    (tmp_path / "n.py").write_text("from m import provider\n\ndef user(): return provider()\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    refs = store.all_refs()
    assert ("n.py", "m.py", "provider", 1) in refs
    store.close()
