"""EN: The 4 consistency invariants + end-to-end acceptance tests.
ZH: 4 ??????? + ????????
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from codeatlas.changelog import write_history_doc
from codeatlas.indexer import run_scan, run_update
from codeatlas.markdown import render_detail_files, render_overview
from codeatlas.storage import Store


# ------------------------------------------------------------- invariants

def check_disk_matches_symbols(store: Store, root: Path) -> None:
    """INV1: every symbol's file exists on disk; no orphan symbol rows."""
    for (fpath,) in store.conn.execute("SELECT DISTINCT file FROM symbols"):
        assert (root / fpath).exists(), f"orphan symbols for missing file: {fpath}"


def check_refs_no_dangling(store: Store) -> None:
    """INV2: refs edges always point to known files on both ends."""
    known = store.known_paths()
    for src, dst, _sym, _cnt in store.all_refs():
        assert src in known, f"dangling ref src: {src}"
        assert dst in known, f"dangling ref dst: {dst}"


def check_update_has_history(store: Store, hist_dir: Path) -> None:
    """INV3: any update that produced changes has a history doc."""
    docs = list(hist_dir.glob("*.md"))
    assert docs, "update with changes must write a history doc"


def check_symbols_fts_consistent(store: Store) -> None:
    """INV4: FTS row count matches symbols row count (when FTS enabled)."""
    if not store.fts_enabled:
        return
    n_sym = store.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    n_fts = store.conn.execute("SELECT COUNT(*) FROM symbols_fts").fetchone()[0]
    assert n_sym == n_fts, f"FTS desync: symbols={n_sym} fts={n_fts}"


# ------------------------------------------------------------- e2e tests

def _touch(p: Path) -> None:
    st = p.stat()
    os.utime(p, (st.st_atime + 5, st.st_mtime + 5))


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
    check_disk_matches_symbols(store, tmp_path)
    check_refs_no_dangling(store)
    check_symbols_fts_consistent(store)

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
    check_disk_matches_symbols(store, tmp_path)
    check_refs_no_dangling(store)
    check_symbols_fts_consistent(store)
    check_update_has_history(store, hist_dir)

    # update 2: delete main.py -> dangling edge must be cleaned
    time.sleep(0.02)
    (src / "main.py").unlink()
    r3 = run_update(tmp_path, store)
    assert any(c.change_type.value == "removed" for c in r3.changes)
    check_refs_no_dangling(store)  # INV2 after deletion
    check_symbols_fts_consistent(store)

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
    (tmp_path / "工具.py").write_text(
        "def 打印(text: str) -> None:\n    '''打印'''\n    print(text)\n", encoding="utf-8"
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store, output_lang="zh")
    check_symbols_fts_consistent(store)
    from codeatlas.cli import _search

    rows = _search(store, "打印", 10)
    assert any("打印" in r[2] for r in rows)
    store.close()
