"""EN: Tests for the MCP server — one sync service-level suite (the tool
bodies are thin delegations) plus async suites over the public MCPServer
API (list_tools / call_tool with CallToolResult).

ZH: MCP server 测试 —— 同步 service 层套件（tool 本体只是薄委托）+ 基于
公开 MCPServer API（list_tools / call_tool，返回 CallToolResult）的异步
套件。

EN: stdout discipline: tools return strings; nothing in service prints.
ZH: stdout 纪律：tool 返回字符串，service 层不打印。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codeatlas import service
from codeatlas.indexer import run_scan
from codeatlas.mcp_server import TOOLS, build_server
from codeatlas.storage import Store

from conftest import PY_SERVICE


# ----------------------------------------------------------------- fixtures

@pytest.fixture()
def indexed_project(sample_project: Path) -> Path:
    """A sample project with a full index AND rendered artifacts."""
    service.scan_project(sample_project, "en")
    return sample_project


# ============================================================ service layer

def test_service_scan_and_overview_file(sample_project: Path):
    result = service.scan_project(sample_project, "en")
    assert result.files_scanned > 0
    assert (sample_project / "CODEATLAS.md").is_file()
    assert (sample_project / ".codeatlas" / "detail").is_dir()


def test_service_update_records_change(indexed_project: Path):
    src = indexed_project / "src" / "service.py"
    src.write_text(
        PY_SERVICE + "\n\ndef extra_helper() -> int:\n    '''Extra.'''\n    return 1\n",
        encoding="utf-8",
    )
    outcome = service.update_project(indexed_project, "en")
    assert not outcome.fell_back
    assert outcome.history_path is not None
    assert len(outcome.result.changes) >= 1


def test_service_update_falls_back_without_index(tmp_path: Path):
    outcome = service.update_project(tmp_path, "en")
    assert outcome.fell_back
    assert (tmp_path / ".codeatlas" / "state.db").is_file()


def test_service_search_fts_and_like(indexed_project: Path):
    rows = service.search_symbols(indexed_project, "process")
    assert any(r["qualified_name"].endswith("process") for r in rows)
    # EN: <3 chars -> LIKE path still returns ranked rows.
    # ZH: <3 字符 -> LIKE 路径仍返回有优先级的行。
    rows2 = service.search_symbols(indexed_project, "pr")
    assert rows2


def test_service_search_no_index(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        service.search_symbols(tmp_path, "process")


def test_service_history_unknown_symbol(indexed_project: Path):
    out = service.format_history(indexed_project, "ghost_symbol")
    assert "No history" in out


def test_service_history_rename_chain(indexed_project: Path):
    src = indexed_project / "src" / "service.py"
    body = src.read_text(encoding="utf-8")
    src.write_text(body.replace("def process(", "def handle_item("), encoding="utf-8")
    service.update_project(indexed_project, "en")
    out = service.format_history(indexed_project, "handle_item")
    assert "handle_item" in out


def test_service_context_load_and_status(indexed_project: Path):
    outcome = service.load_context_page(indexed_project, "process")
    assert outcome.page is not None
    assert "### " in outcome.rendered
    assert outcome.tokens > 0

    st = service.format_status(indexed_project)
    assert "budget:" in st
    assert "process" in st


def test_service_context_load_ambiguous(indexed_project: Path):
    util = indexed_project / "src" / "utils.py"
    util.write_text(
        util.read_text(encoding="utf-8")
        + "\n\ndef process(item_id: int) -> str:\n    '''Also process.'''\n    return 'x'\n",
        encoding="utf-8",
    )
    service.update_project(indexed_project, "en")
    with pytest.raises(service.AmbiguousSymbol) as exc:
        service.load_context_page(indexed_project, "process")
    assert len(exc.value.candidates) >= 2


def test_service_context_load_not_found(indexed_project: Path):
    outcome = service.load_context_page(indexed_project, "no_such_sym")
    assert outcome.page is None


def test_service_evict_pin_semantics(indexed_project: Path):
    service.load_context_page(indexed_project, "process", pin=True)
    with pytest.raises(ValueError):
        service.evict_pages(indexed_project, None)  # single evict needs an id
    # EN: --all keeps pinned; force evicts everything.
    # ZH: --all 保留 pinned；force 全部淘汰。
    msg_keep = service.evict_pages(indexed_project, None, all_pages=True)
    assert "Evicted" in msg_keep
    store = Store(indexed_project / ".codeatlas" / "state.db")
    try:
        entries = store.working_set_entries()
        assert len(entries) == 1 and entries[0].pinned
    finally:
        store.close()
    msg_force = service.evict_pages(indexed_project, None, all_pages=True, force=True)
    assert "Evicted 1" in msg_force


def test_service_doctor_clean_and_violation(indexed_project: Path):
    assert service.doctor_problems(indexed_project) == []
    (indexed_project / "src" / "utils.py").unlink()
    problems = service.doctor_problems(indexed_project)
    assert any("orphan symbols" in p for p in problems)


def test_resolve_root_priority(sample_project: Path, monkeypatch):
    monkeypatch.setenv("CODEATLAS_ROOT", str(sample_project))
    assert service.resolve_root(None) == sample_project.resolve()
    with pytest.raises(FileNotFoundError):
        service.resolve_root(str(sample_project / "no_dir"))


# ============================================================ MCP server API

async def _call(server, name, args):
    result = await server.call_tool(name, args)
    assert not result.is_error, result.content
    return result.content[0].text


async def test_mcp_lists_all_ten_tools():
    server = build_server()
    tools = await server.list_tools()
    assert set(TOOLS).issubset({t.name for t in tools})


async def test_mcp_scan_overview_update_flow(sample_project: Path):
    server = build_server()
    msg = await _call(server, "scan_project", {"root": str(sample_project)})
    assert "Scanned" in msg

    ov = await _call(server, "overview", {"root": str(sample_project)})
    assert "Directory Tree" in ov

    src = sample_project / "src" / "service.py"
    src.write_text(
        PY_SERVICE + "\n\ndef extra_helper() -> int:\n    '''Extra.'''\n    return 1\n",
        encoding="utf-8",
    )
    upd = await _call(server, "update_index", {"root": str(sample_project)})
    assert "Updated" in upd
    assert "1 symbol change(s)" in upd


async def test_mcp_search_returns_json(indexed_project: Path):
    server = build_server()
    out = await _call(server, "search_symbols", {"query": "process", "root": str(indexed_project)})
    rows = json.loads(out)
    assert any(r["qualified_name"].endswith("process") for r in rows)


async def test_mcp_search_no_match_text(indexed_project: Path):
    server = build_server()
    out = await _call(server, "search_symbols", {"query": "zzz_no_such", "root": str(indexed_project)})
    assert "No matches" in out


async def test_mcp_module_detail_found_and_missing(indexed_project: Path):
    server = build_server()
    detail_dir = indexed_project / ".codeatlas" / "detail"
    names = sorted(p.name for p in detail_dir.glob("*.md"))
    module = names[0].rsplit("-", 1)[0]
    out = await _call(server, "module_detail", {"module": module, "root": str(indexed_project)})
    assert "No detail shard" not in out

    miss = await _call(server, "module_detail", {"module": "nope", "root": str(indexed_project)})
    assert "No detail shard for module 'nope'" in miss


async def test_mcp_context_load_ambiguous_json(indexed_project: Path):
    util = indexed_project / "src" / "utils.py"
    util.write_text(
        util.read_text(encoding="utf-8")
        + "\n\ndef process(item_id: int) -> str:\n    '''Also process.'''\n    return 'x'\n",
        encoding="utf-8",
    )
    service.update_project(indexed_project, "en")
    server = build_server()
    out = await _call(server, "context_load", {"symbol": "process", "root": str(indexed_project)})
    data = json.loads(out)
    assert data["error"] == "ambiguous"
    assert len(data["candidates"]) >= 2


async def test_mcp_context_evict_reports(indexed_project: Path):
    server = build_server()
    await _call(server, "context_load", {"symbol": "process", "root": str(indexed_project)})
    out = await _call(server, "context_evict", {"all": True, "root": str(indexed_project)})
    assert "Evicted" in out


async def test_mcp_doctor_clean(indexed_project: Path):
    server = build_server()
    out = await _call(server, "doctor", {"root": str(indexed_project)})
    assert "passed" in out


async def test_mcp_root_env_fallback(indexed_project: Path, monkeypatch):
    monkeypatch.setenv("CODEATLAS_ROOT", str(indexed_project))
    server = build_server()
    ov = await _call(server, "overview", {})
    assert "Directory Tree" in ov


async def test_mcp_root_validation(tmp_path: Path):
    server = build_server()
    out = await _call(server, "overview", {"root": str(tmp_path / "no_dir")})
    assert "Not a directory" in out


async def test_mcp_output_cap(indexed_project: Path, monkeypatch):
    import codeatlas.mcp_server as ms

    monkeypatch.setattr(ms, "OUTPUT_BYTE_CAP", 500)
    server = build_server()
    out = await _call(server, "overview", {"root": str(indexed_project)})
    assert "[truncated at 500 bytes" in out
