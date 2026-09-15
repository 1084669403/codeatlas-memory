"""EN: Virtual-memory core tests — load/touch, eviction, locality, status.
ZH: 虚拟内存核心测试 —— 加载/重载、置换、locality、状态。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from codeatlas.indexer import run_scan, run_update
from codeatlas.memory import (
    AmbiguousSymbol,
    Page,
    WorkingSetEntry,
    _build_page,
    _is_file_page,
    ensure_budget,
    evict,
    locality_of,
    load_budget,
    load_page,
    recency_of,
    render_page,
    render_page_with_store,
    render_working_set,
    save_budget,
    status,
)
from codeatlas.budget import Budget
from codeatlas.storage import Store


def _touch(path: Path) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime + 5, st.st_mtime + 5))


def _scan(tmp_path: Path) -> Store:
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    return store


def _svc_project(tmp_path: Path) -> Path:
    (tmp_path / "svc.py").write_text(
        "def helper(x):\n"
        "    return x\n"
        "\n"
        "class TaskService:\n"
        "    def create(self, item):\n"
        "        payload = helper(item)\n"
        "        self.mark_done(payload)\n"
        "        return payload\n"
        "\n"
        "    def mark_done(self, item):\n"
        "        return bool(item)\n",
        encoding="utf-8",
    )
    return tmp_path


def test_load_and_reload_counts(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    p1 = load_page(store, "svc.TaskService.create")
    assert p1 is not None and p1.granularity == "function"
    page_row = store.get_page("svc.TaskService.create")
    assert page_row[5] == 1  # load_count
    # reload = touch, load_count still increments
    time.sleep(0.02)
    load_page(store, "svc.TaskService.create")
    assert store.get_page("svc.TaskService.create")[5] == 2
    store.close()


def test_reload_is_touch_not_double_count(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper")
    e1 = store.get_working_set_entry("svc.helper")
    time.sleep(0.02)
    load_page(store, "svc.helper")
    e2 = store.get_working_set_entry("svc.helper")
    # tokens refreshed once (not doubled), origin kept
    assert e1.tokens == e2.tokens
    assert e2.last_access_at >= e1.last_access_at
    store.close()


def test_bare_name_ambiguity_lists_candidates(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def run(): pass", encoding="utf-8")
    (tmp_path / "b.py").write_text("def run(): pass", encoding="utf-8")
    store = _scan(tmp_path)
    try:
        load_page(store, "run")
        raise AssertionError("expected AmbiguousSymbol")
    except AmbiguousSymbol as amb:
        assert set(amb.candidates) == {"a.run", "b.run"}
    store.close()


def test_file_page_detection_and_render(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    assert _is_file_page("svc.py") is True
    assert _is_file_page("src/svc.py") is True
    assert _is_file_page("svc.helper") is False
    page = load_page(store, "svc.py")
    assert page is not None and page.granularity == "file"
    text = render_page_with_store(store, page)
    assert "| symbol |" in text and "`svc.helper`" in text
    store.close()


def test_render_page_function_form(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    page = load_page(store, "svc.TaskService.create")
    text = render_page(page)
    assert "### `svc.TaskService.create`" in text
    assert "callers:" not in text or "callees:" in text
    assert "svc.helper" in text  # callees listed
    store.close()


def test_source_excerpt_cap(tmp_path: Path) -> None:
    # a body with many long lines to exceed 800 tokens
    lines = "\n".join(f"    x{i} = '{'v' * 60}'" for i in range(80))
    (tmp_path / "big.py").write_text(f"def big():\n{lines}\n", encoding="utf-8")
    store = _scan(tmp_path)
    page = load_page(store, "big.big", with_source=True)
    from codeatlas.budget import estimate_tokens

    assert page.source
    assert estimate_tokens(page.source) <= 800
    # without --source: empty
    page2 = load_page(store, "big.big")
    assert page2.source == ""
    store.close()


def test_stale_vs_gone_split(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper")
    load_page(store, "svc.TaskService.create")

    time.sleep(0.02)
    # change file (helper's body) -> stale; delete the file later -> gone
    (tmp_path / "svc.py").write_text(
        (tmp_path / "svc.py").read_text(encoding="utf-8").replace("return x", "return x + 0"),
        encoding="utf-8",
    )
    _touch(tmp_path / "svc.py")
    run_update(tmp_path, store)

    from codeatlas.indexer import invalidate_stale as _inv

    _inv(store)
    states = {r.page_id: r.state for r in status(store)}
    # file changed -> version mismatch -> stale
    assert states["svc.helper"] == "stale"
    assert states["svc.TaskService.create"] == "stale"
    store.close()


def test_gone_page_kept_for_status(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper")

    time.sleep(0.02)
    (tmp_path / "svc.py").unlink()
    run_update(tmp_path, store)
    states = {r.page_id: r.state for r in status(store)}
    assert states["svc.helper"] == "gone"  # kept for comparison, not dropped
    store.close()


def test_lru_eviction_order_and_pin_protection(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper")
    time.sleep(0.02)
    load_page(store, "svc.TaskService.create")
    time.sleep(0.02)
    load_page(store, "svc.TaskService.mark_done", pin=True)

    # force a tiny budget: evict 1 page worth of tokens
    b = Budget(total=8000, working_set=10, max_pages=50)
    save_budget(store, b)
    evicted, unsatisfied = ensure_budget(store)
    assert "svc.helper" in evicted  # oldest access evicted first
    assert "svc.TaskService.mark_done" not in evicted  # pinned survives
    # pinned page still resident
    assert store.get_working_set_entry("svc.TaskService.mark_done") is not None
    store.close()


def test_evict_all_keeps_pinned_unless_force(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper")
    load_page(store, "svc.TaskService.create", pin=True)

    from codeatlas.memory import evict as _evict

    entries = [e for e in store.working_set_entries() if not e.pinned]
    total = sum(e.tokens for e in entries)
    evicted, _ = _evict(store, total)
    assert "svc.helper" in evicted
    assert "svc.TaskService.create" not in evicted
    assert store.get_working_set_entry("svc.TaskService.create") is not None
    store.close()


def test_evict_unsatisfied_returned(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper", pin=True)
    # demand far more than all unpinned pages hold
    evicted, unsatisfied = evict(store, 10_000_000)
    assert evicted == []
    assert unsatisfied > 0
    store.close()


def test_layered_locality(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    # anchor inside svc.py at line 5 (create)
    store.set_meta("last_anchor", "svc.py:5")

    same_file = _build_page(store, "svc.helper", None, False)
    # line 1, anchor line 5 -> distance 4 -> high locality
    loc_close = locality_of(store, same_file, 5)
    assert loc_close >= 0.99

    far_page = _build_page(store, "svc.TaskService.create", None, False)
    loc_same = locality_of(store, far_page, 5)
    assert loc_same == 1.0  # exact anchor line

    # cross-file: no relation -> 0.2 tier
    (tmp_path / "other.py").write_text("def lonely(): pass", encoding="utf-8")
    run_scan(tmp_path, store)
    unrelated = _build_page(store, "other.lonely", None, False)
    assert locality_of(store, unrelated, 5) == 0.2
    store.close()


def test_file_page_locality_same_file_constant(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    store.set_meta("last_anchor", "svc.py:5")
    page = _build_page(store, "svc.py", "file", False)
    assert locality_of(store, page, 5) == 1.0
    store.close()


def test_global_anchor_updates_on_load(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.TaskService.mark_done", anchor_line=10)
    raw = store.get_meta("last_anchor")
    assert raw is not None and raw.endswith(":10") and "svc.py" in raw
    store.close()


def test_prefetch_pages_evicted_first(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper")
    load_page(store, "svc.TaskService.create", origin="prefetch")
    time.sleep(0.02)
    load_page(store, "svc.TaskService.mark_done")

    b = Budget(total=8000, working_set=10, max_pages=50)
    save_budget(store, b)
    evicted, _ = ensure_budget(store)
    # with equal recency ordering pressure, the prefetch page is coldest
    assert "svc.TaskService.create" in evicted
    store.close()


def test_working_set_render_order_and_truncation(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper")
    time.sleep(0.02)
    load_page(store, "svc.TaskService.create")
    text = render_working_set(store)
    # most recent first: create's page header comes before helper's
    assert text.index("### `svc.TaskService.create`") < text.index("### `svc.helper`")

    b = Budget(total=10, working_set=6000, max_pages=50)
    save_budget(store, b)
    text2 = render_working_set(store)
    assert "truncated" in text2 or "截断" in text2
    store.close()


def test_scan_clears_working_set(tmp_path: Path) -> None:
    _svc_project(tmp_path)
    store = _scan(tmp_path)
    load_page(store, "svc.helper")
    assert store.working_set_entries()
    # a second full scan rebuilds state -> working set cleared
    run_scan(tmp_path, store)
    assert store.working_set_entries() == []
    # pages statistics survive
    assert store.get_page("svc.helper") is not None
    store.close()


def test_recency_decay() -> None:
    entry = WorkingSetEntry(
        page_id="x",
        loaded_at="2026-09-14T08:00:00+00:00",
        last_access_at="2026-09-14T08:00:00+00:00",
    )
    assert 0.0 < recency_of(entry) <= 1.0


def test_status_version_comparison_loaded_vs_current(tmp_path: Path) -> None:
    """status shows loaded@N vs current index version (plan v6)."""
    _svc_project(tmp_path)
    store = _scan(tmp_path)  # scan bumps index_version to 1
    load_page(store, "svc.helper")
    assert store.index_version() == 1
    assert store.get_page("svc.helper")[6] == 1  # loaded@index_version

    # an update bumps the version; the page was loaded at 1
    time.sleep(0.02)
    (tmp_path / "svc.py").write_text(
        (tmp_path / "svc.py").read_text(encoding="utf-8").replace("return x", "return x + 1"),
        encoding="utf-8",
    )
    _touch(tmp_path / "svc.py")
    run_update(tmp_path, store)
    assert store.index_version() == 2

    rows = {r.page_id: r for r in status(store)}
    entry = rows["svc.helper"]
    assert entry.loaded_index_version == 1
    assert entry.current_index_version == 2
    assert entry.state == "stale"  # file hash mismatch, consistent with versions
    store.close()
