"""Tests for plan memory graphs, fingerprints, staleness, and doctor checks."""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

from typer.testing import CliRunner

from codeatlas.cli import app
from codeatlas.plan_memory import fingerprint_batch_inputs, plan_doctor_problems, plan_doctor_warnings
from codeatlas.plan_workflow import approve_plan, complete_batch, create_plan, mark_batch_stale, record_gate_result, start_batch
from codeatlas.plans import parse_plan_text, plan_graph, render_plan_template
from codeatlas.service import scan_project, update_project


def test_plan_graph_is_deterministic() -> None:
    plan = parse_plan_text(render_plan_template(slug="graph-smoke"))

    first = plan_graph(plan)
    second = plan_graph(plan)

    assert first == second
    assert first["format"] == "mermaid"
    assert first["mermaid"].startswith("flowchart TD")
    assert "B1" in first["mermaid"]
    assert "T1" in first["mermaid"]
    assert first["truncated"] is False
    assert "body" not in first
    assert "sections" not in first


def test_plan_graph_detects_dependency_cycle() -> None:
    text = dedent(
        """
        ---
        schema_version: 1
        id: 2026-09-17-cycle-smoke
        title: Cycle smoke
        status: draft
        created: 2026-09-17T00:00:00Z
        updated_at: 2026-09-17T00:00:00Z
        revision: 1
        content_hash: pending
        revision_type: semantic
        reapproval_required: false
        owner: agent
        last_writer: codex
        files: []
        symbols: []
        context_pages: []
        evidence: []
        change_control: {mode: adaptive}
        engineering:
          profile: product
          architecture_style: none
          standards: []
          quality_gates: [unit-tests]
          plain_language: false
          profile_revision: v13-builtins
        testing:
          approach: test-with-change
          tests: []
          manual_checks: []
        approval: null
        ---

        # Goal

        Detect a cycle.

        # Non-goals

        None.

        # Tasks

        | # | Batch | Task | Depends on | Risk | Files | Symbols | Validation | Status |
        |---|---|---|---|---|---|---|---|---|
        | 1 | B1 | One | 2 | low | none | none | unit-tests gate | pending |
        | 2 | B1 | Two | 1 | low | none | none | unit-tests gate | pending |

        # Validation

        unit-tests gate.

        # Testing strategy

        Structured tests are absent in this graph fixture.

        # Execution notes

        No execution.

        # Engineering requirements

        None.

        # Quality gates

        unit-tests is blocking.

        # Batches

        | Batch | Purpose | Depends on | Status | Last validation |
        |---|---|---|---|---|
        | B1 | Cycle | none | pending | none |
        """
    ).lstrip()
    plan = parse_plan_text(text)

    graph = plan_graph(plan)

    assert graph["cycle_detected"] is True


def test_batch_fingerprint_detects_changes(temp_project: Path) -> None:
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="fingerprint-smoke")
    referenced = temp_project / "tests" / "test_fingerprint_smoke.py"
    referenced.parent.mkdir()
    referenced.write_text("def test_first_task():\n    assert True\n", encoding="utf-8")

    first = fingerprint_batch_inputs(temp_project, created.plan, "B1")
    referenced.write_text("def test_first_task():\n    assert False\n", encoding="utf-8")
    second = fingerprint_batch_inputs(temp_project, created.plan, "B1")

    assert first["fingerprint"].startswith("sha256:")
    assert first["files"] == [
        {"path": "tests/test_fingerprint_smoke.py", "content_hash": first["files"][0]["content_hash"]}
    ]
    assert first["fingerprint"] != second["fingerprint"]


def test_mark_batch_stale(temp_project: Path) -> None:
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="stale-smoke")
    approved = approve_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        approved_by="human-reviewer",
        expected_revision=1,
    )
    started = start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
    )
    referenced = temp_project / "tests" / "test_stale_smoke.py"
    referenced.parent.mkdir()
    referenced.write_text("def test_first_task():\n    assert True\n", encoding="utf-8")
    recorded = record_gate_result(
        temp_project,
        started.plan.path.parent,
        started.plan.id,
        gate_id="unit-tests",
        outcome="passed",
        actor="trusted-runner",
        evidence_kind="runner",
        batch="B1",
        expected_revision=3,
        output_digest="sha256:fixed",
    )
    completed = complete_batch(
        temp_project,
        recorded.plan.path.parent,
        recorded.plan.id,
        batch="B1",
        expected_revision=4,
    )

    marked = mark_batch_stale(
        temp_project,
        completed.plan.path.parent,
        completed.plan.id,
        batch="B1",
        reason="Referenced file changed",
        expected_revision=5,
    )

    assert marked.plan.frontmatter["status"] == "done"
    assert marked.plan.batches[0]["status"] == "stale"
    assert marked.plan.frontmatter["stale_evidence"][-1]["reason"] == "Referenced file changed"
    assert marked.snapshot_path.name == "0006.md"


def test_plan_doctor_detects_drift(temp_project: Path) -> None:
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="doctor-smoke")
    projection = temp_project / ".codeatlas" / "plans" / f"{created.plan.id}.json"
    payload = json.loads(projection.read_text(encoding="utf-8"))
    payload["revision"] = 99
    projection.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    problems = plan_doctor_problems(temp_project, temp_project / "docs" / "plans")

    assert any("projection drift" in problem for problem in problems)



def test_plan_doctor_detects_unbound_gate_evidence(temp_project: Path) -> None:
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="unbound-gate")
    approved = approve_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        approved_by="human-reviewer",
        expected_revision=1,
    )
    start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
    )
    record_gate_result(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        gate_id="unit-tests",
        outcome="passed",
        actor="trusted-runner",
        evidence_kind="runner",
        expected_revision=3,
        output_digest="sha256:fixed",
    )

    problems = plan_doctor_problems(temp_project, temp_project / "docs" / "plans")

    assert any("missing batch" in problem for problem in problems)

def test_plan_doctor_ignores_legacy_markdown(temp_project: Path) -> None:
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="legacy-smoke")
    legacy = temp_project / "docs" / "plans" / "2026-09-16-roadmap-notes.md"
    legacy.write_text("# Legacy roadmap\n\nThis is not a plan.\n", encoding="utf-8")

    problems = plan_doctor_problems(temp_project, temp_project / "docs" / "plans")
    warnings = plan_doctor_warnings(temp_project, temp_project / "docs" / "plans")

    assert problems == []
    assert any(str(legacy.relative_to(temp_project)).replace("\\", "/") in warning for warning in warnings)
    assert created.plan.id


def test_cli_graph_and_stale(temp_project: Path) -> None:
    runner = CliRunner()
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="cli-memory")

    graph = runner.invoke(app, ["plan", "show", created.plan.id, str(temp_project), "--view", "graph", "--json"])
    assert graph.exit_code == 0, graph.output
    graph_payload = json.loads(graph.output)
    assert graph_payload["format"] == "mermaid"
    assert "body" not in graph_payload

    stale = runner.invoke(app, ["plan", "stale", str(temp_project), "--json"])
    assert stale.exit_code == 0, stale.output
    stale_payload = json.loads(stale.output)
    assert stale_payload["items"] == []
    assert "body" not in stale_payload


def test_update_writes_stale_report(sample_project, tmp_path: Path) -> None:
    del tmp_path
    scan_project(sample_project)
    created = create_plan(sample_project, sample_project / "docs" / "plans", slug="update-memory")
    plan_path = created.plan.path
    before = plan_path.read_bytes()

    outcome = update_project(sample_project)

    assert outcome.result.files_parsed >= 0
    report = sample_project / ".codeatlas" / "plans" / "stale-report.json"
    assert report.is_file()
    assert json.loads(report.read_text(encoding="utf-8"))["schema_version"] == 1
    assert plan_path.read_bytes() == before
