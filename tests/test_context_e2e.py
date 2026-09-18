"""EN: End-to-end context VM tests — load/render/stale/evict/ambiguity/scan.
ZH: 端到端 context VM 测试 —— 加载/渲染/stale/淘汰/歧义/scan。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from typer.testing import CliRunner

from codeatlas.cli import app
from codeatlas.indexer import run_scan, run_update
from codeatlas.memory import evict as evict_pages
from codeatlas.memory import status as context_status
from codeatlas.service import context_scope_key
from codeatlas.service import load_context_page
from codeatlas.storage import Store

runner = CliRunner()


def _touch(path: Path) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime + 5, st.st_mtime + 5))


def _make_project(tmp_path: Path) -> Path:
    """Self-contained fixture: no dependency on the demo-todo project."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "svc.py").write_text(
        "def mark_done(item_id: int) -> bool:\n"
        "    return True\n"
        "\n"
        "class TaskService:\n"
        "    def create(self, title: str) -> str:\n"
        "        self.mark_created(title)\n"
        "        return title\n"
        "\n"
        "    def mark_created(self, title: str) -> None:\n"
        "        mark_done(1)\n",
        encoding="utf-8",
    )
    (src / "handler.py").write_text(
        "from svc import TaskService\n"
        "\n"
        "def handle_create(title: str) -> str:\n"
        "    svc = TaskService()\n"
        "    return svc.create(title)\n",
        encoding="utf-8",
    )
    return tmp_path


def _scan(project: Path) -> None:
    r = runner.invoke(app, ["scan", str(project)])
    assert r.exit_code == 0, r.output


def test_load_renders_markdown_with_callers_and_callees(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _scan(project)
    r = runner.invoke(app, ["context", "load", "src.svc.TaskService.create", str(project)])
    assert r.exit_code == 0, r.output
    out = r.output
    # stdout contains the rendered markdown page (deliverable itself, v6)
    assert "### `src.svc.TaskService.create`" in out
    assert "src.svc.mark_done" in out or "mark_created" in out  # callees resolved
    assert "handler.handle_create" in out  # callers resolved


def test_load_bare_name_ambiguous_exit_2(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    (project / "src" / "a.py").write_text("def dup(): pass", encoding="utf-8")
    (project / "src" / "b.py").write_text("def dup(): pass", encoding="utf-8")
    _scan(project)
    r = runner.invoke(app, ["context", "load", "dup", str(project)])
    assert r.exit_code == 2
    assert "src.a.dup" in r.output and "src.b.dup" in r.output


def test_load_json_shape(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _scan(project)
    import json

    r = runner.invoke(
        app, ["context", "load", "src.svc.TaskService.create", str(project), "--json"]
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert set(payload) == {"page", "tokens", "stale"}
    assert payload["page"]["page_id"] == "src.svc.TaskService.create"
    assert payload["tokens"] > 0
    assert payload["stale"] is False


def test_update_marks_stale_and_records_body_lines(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _scan(project)
    r = runner.invoke(app, ["context", "load", "src.svc.mark_done", str(project)])
    assert r.exit_code == 0

    svc = project / "src" / "svc.py"
    time.sleep(0.02)
    svc.write_text(
        svc.read_text(encoding="utf-8").replace("    return True\n", "    return bool(item_id)\n"),
        encoding="utf-8",
    )
    _touch(svc)
    ru = runner.invoke(app, ["update", str(project)])
    assert ru.exit_code == 0

    # history contains the body-level line counts (MVP gap 1)
    hist_files = list((project / ".codeatlas" / "history").glob("*.md"))
    assert hist_files
    text = "\n".join(p.read_text(encoding="utf-8") for p in hist_files)
    assert "+1/-0" in text

    # status shows the stale page (assert via memory.status; the rich table
    # wraps words in box-drawing chars that make substring checks flaky)
    from codeatlas.memory import status as _status

    store = Store(project / ".codeatlas" / "state.db")
    try:
        states = {r.page_id: r.state for r in _status(store)}
    finally:
        store.close()
    assert states.get("src.svc.mark_done") == "stale"


def test_shrinking_budget_evicts_and_warns(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _scan(project)
    for page in ("src.svc.mark_done", "src.svc.TaskService.create", "src.handler.handle_create"):
        r = runner.invoke(app, ["context", "load", page, str(project)])
        assert r.exit_code == 0, r.output

    rb = runner.invoke(app, ["context", "budget", str(project), "--working-set", "10"])
    assert rb.exit_code == 0
    # next load must evict to fit the tiny working-set budget
    rl = runner.invoke(app, ["context", "load", "src.svc.mark_done", str(project)])
    assert rl.exit_code == 0
    assert "evicted" in rl.output
    store = Store(project / ".codeatlas" / "state.db")
    try:
        entries = store.working_set_entries()
        # after eviction at most one page (plus the new load) can remain
        assert len(entries) <= 2
        for e in entries:
            assert e.tokens >= 0
    finally:
        store.close()


def test_scan_clears_working_set_with_notice(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _scan(project)
    r = runner.invoke(app, ["context", "load", "src.svc.mark_done", str(project)])
    assert r.exit_code == 0
    store = Store(project / ".codeatlas" / "state.db")
    try:
        assert store.working_set_entries()
    finally:
        store.close()

    rs = runner.invoke(app, ["scan", str(project)])
    assert rs.exit_code == 0
    assert "working set cleared" in rs.output or "工作集已清空" in rs.output
    store = Store(project / ".codeatlas" / "state.db")
    try:
        assert store.working_set_entries() == []
    finally:
        store.close()


def test_context_commands_require_index(tmp_path: Path) -> None:
    # no scan performed -> exit 1 with the standard message
    for cmd in (["context", "status"], ["doctor"]):
        r = runner.invoke(app, [*cmd, str(tmp_path)])
        assert r.exit_code == 1
        assert "No index found" in r.output or "未找到索引" in r.output


def test_doctor_passes_on_healthy_project(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _scan(project)
    r = runner.invoke(app, ["doctor", str(project)])
    assert r.exit_code == 0, r.output
    assert "passed" in r.output


def test_anchor_written_inside_load_page(tmp_path: Path) -> None:
    """--anchor updates meta['last_anchor'] only after the page resolves."""
    project = _make_project(tmp_path)
    _scan(project)
    r = runner.invoke(
        app, ["context", "load", "src.svc.TaskService.create", str(project), "--anchor", "5"]
    )
    assert r.exit_code == 0, r.output
    store = Store(project / ".codeatlas" / "state.db")
    try:
        anchor = store.get_meta("last_anchor")
    finally:
        store.close()
    assert anchor is not None
    assert anchor.endswith(":5")
    assert "src/svc.py" in anchor  # resolved file, not the raw symbol string


def test_anchor_not_written_on_ambiguity(tmp_path: Path) -> None:
    """A failed (ambiguous) load must not pollute the anchor meta (plan v6)."""
    project = _make_project(tmp_path)
    (project / "src" / "a.py").write_text("def dup(): pass", encoding="utf-8")
    (project / "src" / "b.py").write_text("def dup(): pass", encoding="utf-8")
    _scan(project)
    store = Store(project / ".codeatlas" / "state.db")
    try:
        store.set_meta("last_anchor", "sentinel:9")
    finally:
        store.close()

    r = runner.invoke(app, ["context", "load", "dup", str(project), "--anchor", "5"])
    assert r.exit_code == 2  # ambiguous

    store = Store(project / ".codeatlas" / "state.db")
    try:
        assert store.get_meta("last_anchor") == "sentinel:9"  # untouched
    finally:
        store.close()


def test_scoped_load_status_and_eviction_are_isolated(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _scan(project)
    page_id = "src.svc.mark_done"
    plan_a = load_context_page(project, page_id, plan_id="plan-a")
    plan_b = load_context_page(project, page_id, plan_id="plan-b")

    assert plan_a.page is not None and plan_b.page is not None
    assert plan_a.page.page_id == page_id

    store = Store(project / ".codeatlas" / "state.db")
    try:
        entries = store.working_set_entries()
        assert {entry.plan_id for entry in entries} == {"plan-a", "plan-b"}

        status_a = context_status(store, plan_id="plan-a")
        assert all(row.plan_id == "plan-a" for row in status_a)
        assert page_id in {row.page_id for row in status_a}

        plan_a_tokens = sum(
            entry.tokens for entry in entries if entry.plan_id == "plan-a"
        )
        evicted, unsatisfied = evict_pages(
            store,
            plan_a_tokens,
            plan_id="plan-a",
        )

        assert unsatisfied == 0
        assert evicted
        remaining = store.working_set_entries()
        assert page_id in {entry.page_id for entry in remaining}
        assert {entry.plan_id for entry in remaining if entry.page_id == page_id} == {"plan-b"}
        assert all(entry.plan_id != "plan-a" for entry in remaining)
    finally:
        store.close()


def test_context_scope_cli_and_lease_contract(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    _scan(project)
    page_id = "src.svc.mark_done"
    scope = context_scope_key("session-a", "plan-a", "batch-1")

    load = runner.invoke(
        app,
        [
            "context", "load", page_id, str(project),
            "--session", "session-a",
            "--plan", "plan-a",
            "--batch", "batch-1",
        ],
    )
    assert load.exit_code == 0, load.output

    store = Store(project / ".codeatlas" / "state.db")
    try:
        entry = store.get_working_set_entry(
            page_id,
            session_id="session-a",
            plan_id="plan-a",
            batch_id="batch-1",
        )
        assert entry is not None

        assert store.acquire_working_set_lease(scope, "other-writer", ttl_seconds=60)
    finally:
        store.close()

    blocked = runner.invoke(
        app,
        [
            "context", "load", page_id, str(project),
            "--session", "session-a",
            "--plan", "plan-a",
            "--batch", "batch-1",
        ],
    )
    assert blocked.exit_code == 1
    assert "lease" in blocked.output.lower()

    store = Store(project / ".codeatlas" / "state.db")
    try:
        assert store.release_working_set_lease(scope, "other-writer")
    finally:
        store.close()

    retried = runner.invoke(
        app,
        [
            "context", "load", page_id, str(project),
            "--session", "session-a",
            "--plan", "plan-a",
            "--batch", "batch-1",
        ],
    )
    assert retried.exit_code == 0, retried.output

    status = runner.invoke(
        app,
        ["context", "status", str(project), "--plan", "plan-a"],
    )
    assert status.exit_code == 0, status.output
    assert page_id in status.output
