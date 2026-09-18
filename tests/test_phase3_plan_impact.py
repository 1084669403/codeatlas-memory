import json

import pytest

from typer.testing import CliRunner

from codeatlas.cli import app
from codeatlas.indexer import run_scan
from codeatlas.mcp_server import build_server
from codeatlas.plan_impact import PlanError, compute_plan_impact
from codeatlas.service import plan_impact as service_plan_impact
from codeatlas.plan_memory import plan_doctor_warnings
from codeatlas.service import scan_project, update_project
from codeatlas.storage import Store


def write_plan(
    root,
    *,
    plan_id,
    status,
    files=None,
    symbols=None,
    task_files=None,
    task_symbols=None,
):
    plan_dir = root / "docs" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    files = files or []
    symbols = symbols or []
    task_files = task_files or ["tests/test_phase3_plan_impact.py"]
    task_symbols = task_symbols or []
    frontmatter = [
        "---",
        "schema_version: 1",
        f"id: {plan_id}",
        "title: Impact target",
        f"status: {status}",
        "created: 2026-09-17T00:00:00Z",
        "updated_at: 2026-09-17T00:00:00Z",
        "revision: 1",
        "content_hash: sha256:" + ("0" * 64),
        "revision_type: semantic",
        "reapproval_required: false",
        "owner: human",
        "last_writer: codex",
    ]
    if files:
        frontmatter.append("files:")
        frontmatter.extend(f"  - {item}" for item in files)
    else:
        frontmatter.append("files: []")
    if symbols:
        frontmatter.append("symbols:")
        frontmatter.extend(f"  - {item}" for item in symbols)
    else:
        frontmatter.append("symbols: []")
    frontmatter.extend(
        [
            "context_pages: []",
            "evidence: []",
            "change_control:",
            "  mode: adaptive",
            "  max_files_per_batch: 3",
            "  max_symbols_per_batch: 8",
            "  require_validation_after_batch: true",
            "engineering:",
            "  profile: product",
            "  architecture_style: modular-monolith",
            "  standards:",
            "    - core-plan-logic-is-tool-agnostic",
            "  quality_gates:",
            "    - unit-tests",
            "  plain_language: true",
            "  profile_revision: v13-builtins",
            "testing:",
            "  approach: test-with-change",
            "  manual_checks: []",
            "  tests:",
            "    - test_id: T-001",
            "      kind: unit",
            "      behavior: The target behavior is validated.",
            "      files:",
            "        - tests/test_phase3_plan_impact.py::test_direct_file_impact",
            "      gate_id: unit-tests",
            "      batch: B1",
            "      task: 1",
            "      disposition: reuse",
            "      reason: This fixture proves impact matching itself.",
            "approval: null",
            "---",
            "",
            "# Goal",
            "",
            "Provide a bounded impact fixture.",
            "",
            "# Non-goals",
            "",
            "Do not mutate plans.",
            "",
            "# Tasks",
            "",
            "| # | Batch | Task | Depends on | Risk | Files | Symbols | Validation | Status |",
            "|---|---|---|---|---|---|---|---|---|",
            f"| 1 | B1 | Validate impact matching | none | low | `{task_files[0]}` | {task_symbols[0] if task_symbols else 'none'} | unit-tests gate | done |",
            "",
            "# Validation",
            "",
            "Run the test contract.",
            "",
            "# Testing strategy",
            "",
            "Use focused tests.",
            "",
            "# Execution notes",
            "",
            "One batch at a time.",
            "",
            "# Engineering requirements",
            "",
            "Keep core logic tool agnostic.",
            "",
            "# Quality gates",
            "",
            "unit-tests is blocking.",
            "",
            "# Batches",
            "",
            "| Batch | Purpose | Depends on | Status | Last validation |",
            "|---|---|---|---|---|",
            "| B1 | Validate matching | none | passed | 2026-09-17T00:00:00Z |",
        ]
    )
    path = plan_dir / f"{plan_id}.md"
    path.write_text("\n".join(frontmatter) + "\n", encoding="utf-8", newline="\n")
    return path


def test_direct_file_impact(tmp_path):
    write_plan(
        tmp_path,
        plan_id="open-plan",
        status="executing",
        files=["src/app.py"],
        task_files=["src/app.py"],
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")

    payload = compute_plan_impact(tmp_path, "open-plan", changed_files=["src/app.py"])

    assert payload["plan_id"] == "open-plan"
    assert payload["affected_batches"] == ["B1"]
    assert payload["items"] == [
        {
            "batch": "B1",
            "confidence": 1.0,
            "level": "direct",
            "ref": "src/app.py",
            "source_path": "src/app.py",
            "kind": "file",
            "task": 1,
        }
    ]
    assert payload["truncated"] is False
    assert payload["warnings"] == []


def test_direct_symbol_impact(tmp_path):
    write_plan(
        tmp_path,
        plan_id="open-plan",
        status="executing",
        symbols=["codeatlas.app.run"],
        task_symbols=["codeatlas.app.run"],
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")

    payload = compute_plan_impact(
        tmp_path,
        "open-plan",
        changed_symbols=["codeatlas.app.run"],
        source_paths_by_symbol={"codeatlas.app.run": "src/app.py"},
    )

    assert payload["items"] == [
        {
            "batch": "B1",
            "confidence": 1.0,
            "level": "direct",
            "ref": "codeatlas.app.run",
            "source_path": "src/app.py",
            "kind": "symbol",
            "task": 1,
        }
    ]


def test_only_open_plans_are_eligible(tmp_path):
    write_plan(tmp_path, plan_id="done-plan", status="done", files=["src/app.py"])
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")

    payload = compute_plan_impact(tmp_path, "done-plan", changed_files=["src/app.py"])

    assert payload["items"] == []
    assert payload["affected_batches"] == []
    assert payload["warnings"] == [
        {"code": "PLAN_NOT_OPEN", "message": "Done plans are excluded from new impact work."}
    ]


def test_indirect_impact_is_bounded(tmp_path):
    (tmp_path / "app.py").write_text("def target():\n    helper()\n", encoding="utf-8")
    (tmp_path / "lib.py").write_text("def helper(): pass\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    try:
        run_scan(tmp_path, store)
    finally:
        store.close()
    write_plan(
        tmp_path,
        plan_id="open-plan",
        status="executing",
        symbols=["app.target"],
        task_files=["app.py"],
        task_symbols=["app.target"],
    )

    payload = compute_plan_impact(
        tmp_path,
        "open-plan",
        changed_symbols=["lib.helper"],
        use_index=True,
        max_graph_depth=1,
    )

    assert payload["index_available"] is True
    indirect = [item for item in payload["items"] if item["level"] == "indirect"]
    assert indirect == [
        {
            "batch": "B1",
            "changed_ref": "lib.helper",
            "confidence": 0.85,
            "direction": "caller",
            "graph_depth": 1,
            "kind": "symbol",
            "level": "indirect",
            "ref": "app.target",
            "source_path": "app.py",
            "task": 1,
        }
    ]


def test_possible_impact_is_scored_and_bounded(tmp_path):
    (tmp_path / "view.py").write_text("def renderer(): pass\n", encoding="utf-8")
    (tmp_path / "render.py").write_text("def render(): pass\n", encoding="utf-8")
    store = Store(tmp_path / ".codeatlas" / "state.db")
    try:
        run_scan(tmp_path, store)
    finally:
        store.close()
    write_plan(
        tmp_path,
        plan_id="open-plan",
        status="executing",
        symbols=["view.renderer"],
        task_files=["view.py"],
        task_symbols=["view.renderer"],
    )

    payload = compute_plan_impact(
        tmp_path,
        "open-plan",
        changed_symbols=["view.render"],
        use_index=True,
        max_possible=3,
    )

    possible = [item for item in payload["items"] if item["level"] == "possible"]
    assert possible == [
        {
            "batch": "B1",
            "changed_ref": "view.render",
            "confidence": 0.55,
            "kind": "symbol",
            "level": "possible",
            "reason": "lexical overlap: view",
            "ref": "view.renderer",
            "source_path": "view.py",
            "task": 1,
        }
    ]
    assert payload["limits"]["max_possible"] == 3


def test_missing_index_and_plan_return_stable_errors(tmp_path):
    write_plan(tmp_path, plan_id="open-plan", status="approved")

    payload = compute_plan_impact(
        tmp_path,
        "open-plan",
        changed_symbols=["missing.symbol"],
        use_index=True,
    )

    assert payload["index_available"] is False
    assert payload["warnings"] == [
        {"code": "INDEX_NOT_FOUND", "message": "No index is available for indirect or possible impact."}
    ]

    with pytest.raises(PlanError) as raised:
        compute_plan_impact(tmp_path, "missing-plan")
    assert raised.value.code == "PLAN_NOT_FOUND"


def test_cli_plan_impact_reports_direct_match(tmp_path):
    write_plan(
        tmp_path,
        plan_id="open-plan",
        status="executing",
        files=["src/app.py"],
        task_files=["src/app.py"],
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")
    runner = CliRunner()

    json_result = runner.invoke(
        app,
        [
            "plan", "impact", "open-plan", str(tmp_path),
            "--changed-file", "src/app.py", "--json",
        ],
    )
    assert json_result.exit_code == 0, json_result.output
    payload = json.loads(json_result.output)
    assert payload["affected_batches"] == ["B1"]
    assert payload["items"][0]["ref"] == "src/app.py"

    text_result = runner.invoke(
        app,
        ["plan", "impact", "open-plan", str(tmp_path), "--changed-file", "src/app.py"],
    )
    assert text_result.exit_code == 0, text_result.output
    assert "open-plan" in text_result.output
    assert "B1" in text_result.output
    assert "src/app.py" in text_result.output


def test_service_plan_impact_uses_the_core_engine(tmp_path):
    write_plan(
        tmp_path,
        plan_id="open-plan",
        status="approved",
        files=["src/app.py"],
        task_files=["src/app.py"],
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("value = 1\n", encoding="utf-8")

    payload = service_plan_impact(
        tmp_path,
        "open-plan",
        changed_files=["src/app.py"],
    )

    assert payload["schema_version"] == 1
    assert payload["affected_batches"] == ["B1"]


def test_update_writes_impact_report(sample_project):
    scan_project(sample_project)
    write_plan(
        sample_project,
        plan_id="open-plan",
        status="executing",
        files=["src/service.py"],
        task_files=["src/service.py"],
    )
    plan_path = sample_project / "docs" / "plans" / "open-plan.md"
    plan_before = plan_path.read_bytes()
    service_path = sample_project / "src" / "service.py"
    service_path.write_text(service_path.read_text(encoding="utf-8") + "\n\ndef touched(): pass\n", encoding="utf-8")

    outcome = update_project(sample_project)

    assert outcome.impact_report_path is not None
    report = sample_project / ".codeatlas" / "plans" / "impact-report.json"
    assert outcome.impact_report_path == report
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["affected_plans"][0]["plan_id"] == "open-plan"
    assert payload["affected_plans"][0]["affected_batches"] == ["B1"]
    assert any(item["ref"] == "src/service.py" for item in payload["affected_plans"][0]["items"])
    assert plan_path.read_bytes() == plan_before


def test_malformed_plan_is_update_warning(sample_project):
    scan_project(sample_project)
    (sample_project / "docs" / "plans").mkdir(parents=True, exist_ok=True)
    broken_path = sample_project / "docs" / "plans" / "broken-plan.md"
    broken_path.write_text("---\nfiles: [unclosed\n---\nBroken plan.\n", encoding="utf-8")
    service_path = sample_project / "src" / "utils.py"
    service_path.write_text(service_path.read_text(encoding="utf-8") + "\n\ndef touched(): pass\n", encoding="utf-8")

    outcome = update_project(sample_project)

    assert outcome.impact_report_path is not None
    payload = json.loads(outcome.impact_report_path.read_text(encoding="utf-8"))
    assert any(warning["code"] == "PLAN_SCHEMA_INVALID" for warning in payload["warnings"])


def test_update_cli_prints_affected_plans(sample_project):
    scan_project(sample_project)
    write_plan(
        sample_project,
        plan_id="open-plan",
        status="executing",
        files=["src/service.py"],
        task_files=["src/service.py"],
    )
    service_path = sample_project / "src" / "service.py"
    service_path.write_text(
        service_path.read_text(encoding="utf-8") + "\n\ndef cli_touched(): pass\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    result = runner.invoke(app, ["update", str(sample_project)])

    assert result.exit_code == 0, result.output
    assert "Affected open plans" in result.output
    assert "open-plan" in result.output
    assert "B1" in result.output
    assert "src/service.py" in result.output


async def test_mcp_update_reports_affected_plans(sample_project):
    scan_project(sample_project)
    write_plan(
        sample_project,
        plan_id="open-plan",
        status="executing",
        files=["src/service.py"],
        task_files=["src/service.py"],
    )
    service_path = sample_project / "src" / "service.py"
    service_path.write_text(
        service_path.read_text(encoding="utf-8") + "\n\ndef mcp_touched(): pass\n",
        encoding="utf-8",
    )
    server = build_server()

    result = await server.call_tool("update_index", {"root": str(sample_project)})

    assert not result.is_error, result.content
    output = result.content[0].text
    assert "Affected plans: open-plan (B1)" in output


def test_doctor_reports_unresolved_plan_symbols(sample_project):
    scan_project(sample_project)
    (sample_project / "tests").mkdir()
    (sample_project / "tests" / "test_phase3_plan_impact.py").write_text("", encoding="utf-8")
    write_plan(
        sample_project,
        plan_id="open-plan",
        status="approved",
        files=["src/service.py"],
        symbols=["does.not.exist", "service"],
        task_files=["src/service.py"],
        task_symbols=["does.not.exist"],
    )

    warnings = plan_doctor_warnings(
        sample_project,
        sample_project / "docs" / "plans",
    )

    assert any("plan unresolved symbol: open-plan: does.not.exist" in warning for warning in warnings)
    assert not any("plan unresolved symbol: open-plan: service" in warning for warning in warnings)
