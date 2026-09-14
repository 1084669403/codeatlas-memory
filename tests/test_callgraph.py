"""EN: Call-graph tests — resolution, incrementality, health checks.
ZH: 调用图测试 —— 解析、增量、健康检查。
"""

from __future__ import annotations

import os
from pathlib import Path

from codeatlas.callgraph import (
    callees_of,
    callers_of,
    check_callgraph_health,
    rebuild_call_edges,
)
from codeatlas.indexer import run_scan, run_update
from codeatlas.storage import Store


def _touch(path: Path) -> None:
    st = path.stat()
    os.utime(path, (st.st_atime + 5, st.st_mtime + 5))


def test_same_file_call_resolution(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def helper(): pass\n\ndef main():\n    helper()\n", encoding="utf-8"
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    assert callees_of(store, "a.main") == ["a.helper"]
    assert callers_of(store, "a.helper") == ["a.main"]
    store.close()


def test_cross_module_import_call(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def provider(): pass", encoding="utf-8")
    (tmp_path / "n.py").write_text(
        "from m import provider\n\ndef user(): return provider()\n", encoding="utf-8"
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    assert callees_of(store, "n.user") == ["m.provider"]
    assert callers_of(store, "m.provider") == ["n.user"]
    store.close()


def test_self_method_resolution(tmp_path: Path) -> None:
    src = (
        "class TaskService:\n"
        "    def create(self):\n"
        "        self.mark_done()\n"
        "\n"
        "    def mark_done(self):\n"
        "        return True\n"
    )
    (tmp_path / "svc.py").write_text(src, encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    assert callees_of(store, "svc.TaskService.create") == ["svc.TaskService.mark_done"]
    store.close()


def test_ts_call_resolution(tmp_path: Path) -> None:
    (tmp_path / "helper.ts").write_text(
        "export function helper(msg: string): string {\n    return msg;\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "index.ts").write_text(
        'import { helper } from "./helper";\n'
        "export function run(): void {\n    helper('x');\n}\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    assert callees_of(store, "index.run") == ["helper.helper"]
    store.close()


def test_unresolved_calls_dropped_and_rate_recorded(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def main():\n    totally_unknown()\n    print('x')\n", encoding="utf-8"
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    # nothing resolved: unknown bare name and print (builtin) both dropped
    assert callees_of(store, "a.main") == []
    assert store.get_meta("call_resolution_total") == "2"
    assert store.get_meta("call_resolution_rate") is not None
    store.close()


def test_module_level_calls_not_collected(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def f(): pass\n\nf()  # module-level call: out of scope (P2-11)\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    assert store.all_raw_calls() == []
    store.close()


def test_incremental_update_keeps_other_files_raw_calls(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def provider(): pass", encoding="utf-8")
    (tmp_path / "n.py").write_text(
        "from m import provider\n\ndef user(): return provider()\n", encoding="utf-8"
    )
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    n_raw_before = len(store.all_raw_calls())

    # change m.py only — n.py's raw calls must survive (plan P0-2)
    import time

    time.sleep(0.02)
    (tmp_path / "m.py").write_text(
        "def provider(): return 1\n\ndef extra(): pass", encoding="utf-8"
    )
    _touch(tmp_path / "m.py")
    run_update(tmp_path, store)

    assert len(store.all_raw_calls()) >= n_raw_before
    # call_edges rebuilt and still complete
    assert callees_of(store, "n.user") == ["m.provider"]
    assert callers_of(store, "m.provider") == ["n.user"]
    store.close()


def test_deleted_file_raw_calls_swept(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(): pass\n\ndef g(): f()\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    run_scan(tmp_path, store)
    assert store.all_raw_calls()

    import time

    time.sleep(0.02)
    (tmp_path / "a.py").unlink()
    run_update(tmp_path, store)
    assert store.all_raw_calls() == []
    assert store.all_call_edges() == []
    # health check finds no orphans
    rate, problems = check_callgraph_health(store)
    assert problems == []
    store.close()
