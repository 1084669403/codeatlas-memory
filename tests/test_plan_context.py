"""Tests for deterministic plan-context retrieval."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from codeatlas.cli import app
from codeatlas.plan_context import retrieve_plan_context
from codeatlas.service import scan_project
from codeatlas.mcp_server import build_server


def test_missing_index_returns_bootstrap_hint(temp_project: Path) -> None:
    outcome = retrieve_plan_context(temp_project, "add token refresh")

    assert outcome["status"] == "bootstrap_required"
    assert outcome["error_code"] == "NO_INDEX"
    assert outcome["evidence"] == []
    assert "codeatlas scan" in outcome["hint"]


def test_symbol_evidence_is_deterministic_and_stale_aware(sample_project) -> None:
    scan_project(sample_project)
    first = retrieve_plan_context(sample_project, "process item")
    second = retrieve_plan_context(sample_project, "process item")

    assert first["status"] == "ok"
    assert first["evidence"]
    assert first["evidence"] == second["evidence"]
    symbol = first["evidence"][0]
    for field in {"evidence_id", "kind", "ref", "reason", "confidence", "stale", "source_path"}:
        assert field in symbol
    assert symbol["kind"] == "symbol"
    assert symbol["stale"] is False
    assert first["impact_scope"]["symbols"]

    path = sample_project / first["evidence"][0]["source_path"]
    path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    stale = retrieve_plan_context(sample_project, "process item")
    assert any(item["stale"] for item in stale["evidence"])


def test_retrieval_is_bounded_and_ranks_neighbours(temp_project: Path) -> None:
    root = temp_project.resolve()
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "service.py").write_text(
        "def process(item_id: int) -> str:\n    return str(item_id)\n",
        encoding="utf-8",
    )
    (root / "src" / "main.py").write_text(
        "from .service import process\n\ndef main() -> None:\n    process(1)\n",
        encoding="utf-8",
    )
    (root / "src" / "worker.py").write_text(
        "from .service import process\n\ndef run() -> None:\n    process(2)\n",
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text(
        "# Agent conventions\n\nUse process boundaries consistently.\n",
        encoding="utf-8",
    )
    scan_project(root)

    outcome = retrieve_plan_context(root, "process", max_evidence=2)

    assert len(outcome["evidence"]) <= 2
    assert outcome["evidence"][0]["kind"] == "symbol"
    assert outcome["evidence"][0]["ref"] == "src.service.process"
    assert any(item["kind"] == "call-neighbor" for item in outcome["evidence"])
    assert outcome["truncated"] is True


def test_convention_evidence_is_included(temp_project: Path) -> None:
    root = temp_project.resolve()
    (root / "src").mkdir()
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "api.py").write_text("def refresh(): ...\n", encoding="utf-8")
    (root / "AGENTS.md").write_text(
        "# Conventions\n\nToken refresh handlers must return explicit errors.\n",
        encoding="utf-8",
    )
    scan_project(root)

    outcome = retrieve_plan_context(root, "token refresh")

    assert any(
        item["kind"] == "convention" and item["source_path"] == "AGENTS.md"
        for item in outcome["evidence"]
    )


def test_cli_plan_context(sample_project) -> None:
    scan_project(sample_project)
    runner = CliRunner()

    payload = runner.invoke(app, ["plan", "context", "process item", str(sample_project), "--json"])
    assert payload.exit_code == 0, payload.output
    parsed = json.loads(payload.output)
    assert parsed["status"] == "ok"
    assert parsed["evidence"]

    rendered = runner.invoke(app, ["plan", "context", "process item", str(sample_project)])
    assert rendered.exit_code == 0, rendered.output
    assert "Evidence" in rendered.output
    assert "process" in rendered.output


async def test_mcp_plan_context(sample_project: Path) -> None:
    scan_project(sample_project)
    server = build_server()
    result = await server.call_tool("plan_context", {"query": "process item", "root": str(sample_project)})
    assert not result.is_error
    parsed = json.loads(result.content[0].text)
    assert parsed["status"] == "ok"
    assert parsed["evidence"]
