"""EN: History document tests: content, old->new, interval warning, gitignore.
ZH: 历史文档测试：内容、old→new、间隔警示、gitignore。
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.changelog import write_codeatlas_gitignore, write_history_doc
from codeatlas.indexer import run_scan, run_update
from codeatlas.models import ChangeRecord, ChangeType
from codeatlas.storage import Store


def test_history_doc_contains_old_new(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(a: int) -> int:\n    return a\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    import os
    import time

    time.sleep(0.02)
    st = (tmp_path / "a.py").stat()
    os.utime(tmp_path / "a.py", (st.st_atime + 5, st.st_mtime + 5))
    (tmp_path / "a.py").write_text("def f(a: int, b: int = 0) -> int:\n    return a + b\n", encoding="utf-8")
    r = run_update(tmp_path, store)
    hist = tmp_path / ".codeatlas" / "history"
    out = write_history_doc(hist, store, r.changes, r.timestamp, lang="zh")
    text = out.read_text(encoding="utf-8")
    assert "签名变更" in text
    assert "`def f(a: int) -> int`" in text  # old
    assert "`def f(a: int, b: int = 0) -> int`" in text  # new
    store.close()


def test_history_doc_interval_warning(tmp_path: Path) -> None:
    store = Store(tmp_path / ".codeatlas" / "state.db")
    old_ts = "2026-09-14T08:00:00+00:00"
    new_ts = "2026-09-14T09:00:00+00:00"  # 60 min later
    store.append_changes(
        [ChangeRecord(ts=old_ts, file="a.py", symbol="m.x", change_type=ChangeType.ADDED)]
    )
    out = write_history_doc(
        tmp_path / "history", store, [], new_ts, lang="en"
    )
    text = out.read_text(encoding="utf-8")
    assert "may not cover all intermediate states" in text
    store.close()


def test_history_doc_no_changes(tmp_path: Path) -> None:
    store = Store(tmp_path / ".codeatlas" / "state.db")
    out = write_history_doc(tmp_path / "history", store, [], "2026-09-14T09:00:00+00:00", lang="zh")
    text = out.read_text(encoding="utf-8")
    assert "无符号变更" in text
    store.close()


def test_codeatlas_gitignore_keeps_history(tmp_path: Path) -> None:
    write_codeatlas_gitignore(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "!history/" in text  # history committed by design
    assert text.index("*") < text.index("!history/")  # ignore-all first


def test_every_update_writes_history(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    import os
    import time

    time.sleep(0.02)
    st = (tmp_path / "a.py").stat()
    os.utime(tmp_path / "a.py", (st.st_atime + 5, st.st_mtime + 5))
    (tmp_path / "a.py").write_text("def f(): pass\ndef g(): pass", encoding="utf-8")
    r = run_update(tmp_path, store)
    assert r.changes, "update must produce change records"
    hist = tmp_path / ".codeatlas" / "history"
    write_history_doc(hist, store, r.changes, r.timestamp, lang="en")
    assert list(hist.glob("*.md")), "update must have a history doc"
    store.close()
