"""EN: Consistency invariants (via consistency.py) + end-to-end acceptance.
ZH: ???????? consistency.py?+ ????????
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from codeatlas.changelog import write_history_doc
from codeatlas.consistency import (
    check_disk_symbols,
    check_fts_sync,
    check_refs_dangling,
    run_all_checks,
)
from codeatlas.indexer import run_scan, run_update
from codeatlas.markdown import render_detail_files, render_overview
from codeatlas.storage import Store


# ------------------------------------------------------------- invariants
# EN: refactored to call consistency.py pure functions (plan step 11/14).
# ZH: ????? consistency.py ??????? 11/14 ???


def test_full_lifecycle_and_invariants(tmp_path: Path) -> None:
    """Acceptance: scan -> update x2 -> invariants hold at every step."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "service.py").write_text("def process(i: int) -> str:\n    return str(i)\n", encoding="utf-8")
    (src / "main.py").write_text("from service import process\n\ndef run(): process(1)\n", encoding="utf-8")

    codeatlas_dir = tmp_path / ".codeatlas"
    hist_dir = codeatlas_dir / "history"
    store = Store(codeatlas_dir / "state.db")

    # scan
    r1 = run_scan(tmp_path, store, output_lang="en")
    assert r1.files_parsed == 2
    assert r1.symbols_found == 2  # process + run
    assert check_disk_symbols(store, tmp_path) == []
    assert check_refs_dangling(store) == []
    assert check_fts_sync(store) == []

    # update 1: signature change + new function
    time.sleep(0.02)
    (src / "service.py").write_text(
        "def process(i: int, tag: str = '') -> str:\n    return str(i) + tag\n\n\ndef extra(): pass\n",
        encoding="utf-8",
    )
    _touch(src / "service.py")
    r2 = run_update(tmp_path, store)
    assert r2.changes
    write_history_doc(hist_dir, store, r2.changes, r2.timestamp, lang="en")
    assert check_disk_symbols(store, tmp_path) == []
    assert check_refs_dangling(store) == []
    assert check_fts_sync(store) == []

    # update 2: delete main.py -> dangling edge must be cleaned
    time.sleep(0.02)
    (src / "main.py").unlink()
    r3 = run_update(tmp_path, store)
    assert any(c.change_type.value == "removed" for c in r3.changes)
    assert check_refs_dangling(store) == []  # INV2 after deletion
    assert check_fts_sync(store) == []

    # full render pipeline still works
    render_detail_files(store, codeatlas_dir / "detail", "en")
    render_overview(tmp_path, store, r3, tmp_path / "CODEATLAS.md", lang="en")
    assert (tmp_path / "CODEATLAS.md").exists()
    store.close()


def test_self_scan_excludes_codeatlas_dir(tmp_path: Path) -> None:
    """Bootstrapping guard: scanning a project never indexes .codeatlas/."""
    (tmp_path / "a.py").write_text("def f(): pass", encoding="utf-8")
    (tmp_path / ".codeatlas").mkdir()
    (tmp_path / ".codeatlas" / "junk.py").write_text("def bad(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    paths = store.known_paths()
    assert "a.py" in paths
    assert not any(p.startswith(".codeatlas") for p in paths)
    store.close()


def test_chinese_filename_end_to_end(tmp_path: Path) -> None:
    """Chinese filenames flow through scan -> query -> history untouched."""
    # EN: ??.py / ?? written as escapes to survive editor round-trips.
    # ZH: ????????Windows/zh-CN ??????
    cname = "\u5de5\u5177"  # ??
    csym = "\u6253\u5370"  # ??
    (tmp_path / f"{cname}.py").write_text(
        f"def {csym}(text: str) -> None:\n    '''{csym}'''\n    print(text)\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store, output_lang="zh")
    assert check_fts_sync(store) == []
    from codeatlas.cli import _search

    rows = _search(store, csym, 10)
    assert any(csym in r[2] for r in rows)
    store.close()


# ------------------------------------------------------- new v6 invariants


def test_deleted_file_leaves_no_raw_calls_orphans(tmp_path: Path) -> None:
    """INV5: deleting a file sweeps its raw_calls (no orphans for doctor)."""
    (tmp_path / "a.py").write_text("def f(): pass\n\ndef g(): f()\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    assert store.all_raw_calls()

    time.sleep(0.02)
    (tmp_path / "a.py").unlink()
    run_update(tmp_path, store)
    # doctor's callgraph check must be silent
    from codeatlas.consistency import check_callgraph

    assert check_callgraph(store) == []
    store.close()


def test_scan_clears_working_set(tmp_path: Path) -> None:
    """scan semantics: full rebuild clears the working set (pages kept)."""
    (tmp_path / "a.py").write_text("def f(): pass", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    from codeatlas.memory import load_page

    load_page(store, "a.f")
    assert store.working_set_entries()
    run_scan(tmp_path, store)
    assert store.working_set_entries() == []
    assert store.get_page("a.f") is not None  # stats survive
    store.close()


def test_run_all_checks_clean_project(tmp_path: Path) -> None:
    """The aggregate doctor check passes on a healthy project."""
    (tmp_path / "a.py").write_text("def f(): pass\n\ndef g(): f()\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    problems = run_all_checks(store, tmp_path, tmp_path / ".codeatlas" / "history")
    assert problems == [], problems
    store.close()


def _touch(p: Path) -> None:
    st = p.stat()
    os.utime(p, (st.st_atime + 5, st.st_mtime + 5))
