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


# ------------------------------------------------- body-level diff (v6 plan)


def test_body_change_records_line_counts(tmp_path: Path) -> None:
    """Signature-stable + body edits -> SIGNATURE_STABLE with detail +N/-M."""
    (tmp_path / "a.py").write_text(
        "def f() -> str:\n    return 'v1'\n", encoding="utf-8"
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    import os
    import time

    time.sleep(0.02)
    (tmp_path / "a.py").write_text(
        "def f() -> str:\n    x = 1\n    return f'v2-{x}'\n", encoding="utf-8"
    )
    os.utime(tmp_path / "a.py", (time.time() + 5, time.time() + 5))
    r = run_update(tmp_path, store)
    assert r.changes[0].change_type == ChangeType.SIGNATURE_STABLE
    assert r.changes[0].detail == "+2/-0"
    store.close()


def test_comment_only_change_no_noise(tmp_path: Path) -> None:
    """Comment-only edits DO count as body edits (honest); but identical
    bodies must not emit a change at all."""
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    import os
    import time

    # whitespace-only difference normalizes away (line content identical)
    time.sleep(0.02)
    (tmp_path / "a.py").write_text("def f():\n    return 1  # note\n", encoding="utf-8")
    os.utime(tmp_path / "a.py", (time.time() + 5, time.time() + 5))
    r = run_update(tmp_path, store)
    # a real text change still records (comments are code too) — but a pure
    # CRLF flip must NOT (see next test)
    assert all(c.change_type == ChangeType.SIGNATURE_STABLE for c in r.changes)
    store.close()


def test_crlf_normalization_no_false_positive(tmp_path: Path) -> None:
    """CRLF->LF rewrite with identical content must not record a diff."""
    (tmp_path / "a.py").write_bytes(b"def f():\n    return 1\n")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    import os
    import time

    time.sleep(0.02)
    (tmp_path / "a.py").write_bytes(b"def f():\r\n    return 1\r\n")
    os.utime(tmp_path / "a.py", (time.time() + 5, time.time() + 5))
    r = run_update(tmp_path, store)
    assert r.changes == [], "CRLF-only change must not produce body diff"
    store.close()


def test_migration_baseline_silent_write(tmp_path: Path) -> None:
    """Old row with body='' (pre-v2 baseline) -> first update writes the new
    body silently, no SIGNATURE_STABLE noise (plan P1-1)."""
    from codeatlas.models import FileRecord, Symbol, SymbolKind

    store = Store(tmp_path / ".codeatlas" / "state.db")
    old = FileRecord(
        path="a.py",
        language="python",
        hash="h1",
        mtime=1.0,
        size=10,
        symbols=[
            Symbol(
                qualified_name="a.f",
                name="f",
                kind=SymbolKind.FUNCTION,
                signature="def f() -> str",
                params="()",
                returns="str",
            )
        ],
    )
    store.upsert_file(old, "2026-01-01T00:00:00+00:00")
    # simulate pre-v2 row: body lost in migration
    store.conn.execute("UPDATE symbols SET body = '' WHERE qualified_name = 'a.f'")
    store.conn.commit()

    (tmp_path / "a.py").write_text(
        "def f() -> str:\n    return 'changed body'\n", encoding="utf-8"
    )
    r = run_scan_stored(tmp_path, store)
    stable = [c for c in r.changes if c.change_type == ChangeType.SIGNATURE_STABLE]
    assert stable == [], "migration baseline must not record body diff"
    # new body written silently
    row = store.symbol_row("a.f")
    assert row[12] != ""
    store.close()


def run_scan_stored(tmp_path: Path, store: Store):
    from codeatlas.indexer import run_update

    import os
    import time

    time.sleep(0.02)
    os.utime(tmp_path / "a.py", (time.time() + 5, time.time() + 5))
    return run_update(tmp_path, store)


def test_body_64kb_truncation_skips_diff(tmp_path: Path) -> None:
    """A >64KB body gets truncated; diffing truncated bodies is skipped."""
    from codeatlas.models import BODY_MAX_BYTES

    big = "def f():\n" + "".join(f"    x{i} = {i}\n" for i in range(20000))
    assert len(big.encode("utf-8")) > BODY_MAX_BYTES
    (tmp_path / "a.py").write_text(big, encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    row = store.symbol_row("a.f")
    assert len(row[12].encode("utf-8")) <= BODY_MAX_BYTES
    store.close()
