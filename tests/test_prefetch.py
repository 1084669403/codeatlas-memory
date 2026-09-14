"""EN: Prefetch tests — neighbour selection, budget caps, no pollution.
ZH: 预取测试 —— 邻居选择、预算上限、不污染。
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.indexer import run_scan
from codeatlas.memory import _build_page, load_page
from codeatlas.prefetch import neighbors, prefetch
from codeatlas.storage import Store


def _scan(tmp_path: Path) -> Store:
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    return store


def _project(tmp_path: Path) -> None:
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
    (tmp_path / "handler.py").write_text(
        "from svc import TaskService\n"
        "\n"
        "def handle_create():\n"
        "    return TaskService().create(1)\n",
        encoding="utf-8",
    )


def test_callers_rank_above_callees(tmp_path: Path) -> None:
    _project(tmp_path)
    store = _scan(tmp_path)
    page = _build_page(store, "svc.TaskService.create", None, False)
    cands = neighbors(store, page)
    ids = [c[0] for c in cands]
    # caller handle_create first, then callees helper / mark_done
    assert ids[0] == "handler.handle_create"
    assert "svc.helper" in ids and "svc.TaskService.mark_done" in ids
    store.close()


def test_prefetch_loads_neighbours_with_prefetch_origin(tmp_path: Path) -> None:
    _project(tmp_path)
    store = _scan(tmp_path)
    page = load_page(store, "svc.TaskService.create")
    loaded = prefetch(store, page)
    assert loaded, "prefetch must load at least one neighbour"
    for page_id in loaded:
        entry = store.get_working_set_entry(page_id)
        assert entry is not None and entry.origin == "prefetch"
    # the loaded page itself keeps origin=load
    assert store.get_working_set_entry("svc.TaskService.create").origin == "load"
    store.close()


def test_prefetch_respects_max_pages(tmp_path: Path) -> None:
    _project(tmp_path)
    store = _scan(tmp_path)
    page = load_page(store, "svc.TaskService.create")
    loaded = prefetch(store, page, max_pages=1)
    assert len(loaded) <= 1
    store.close()


def test_prefetch_stops_when_page_budget_full(tmp_path: Path) -> None:
    _project(tmp_path)
    store = _scan(tmp_path)
    from codeatlas.memory import load_budget, save_budget
    from codeatlas.budget import Budget

    save_budget(store, Budget(total=8000, working_set=6000, max_pages=1))
    page = load_page(store, "svc.TaskService.create")
    loaded = prefetch(store, page)
    assert loaded == []  # already at max_pages=1
    store.close()


def test_file_page_uses_refs_neighbours(tmp_path: Path) -> None:
    _project(tmp_path)
    store = _scan(tmp_path)
    page = _build_page(store, "handler.py", "file", False)
    cands = neighbors(store, page)
    ids = [c[0] for c in cands]
    # refs neighbour svc.py via the import, plus same-directory files
    assert "svc.py" in ids
    store.close()


def test_prefetch_does_not_evict_loaded_page(tmp_path: Path) -> None:
    _project(tmp_path)
    store = _scan(tmp_path)
    page = load_page(store, "svc.TaskService.create", pin=True)
    prefetch(store, page)
    assert store.get_working_set_entry("svc.TaskService.create") is not None
    store.close()
