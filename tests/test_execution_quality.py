"""Tests for safe plan execution, gate evidence, and test-contract completion."""

from __future__ import annotations

import sys
import json
from pathlib import Path
import yaml

import pytest
from typer.testing import CliRunner

from codeatlas.gates import run_gate
from codeatlas.plan_workflow import approve_plan, canonical_plan_hash, complete_batch, create_plan, record_gate_result, revise_plan, start_batch
from codeatlas.plans import PlanError, find_plan
from codeatlas.cli import app


def _approved_plan(temp_project: Path):
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="execution-smoke")
    return approve_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        approved_by="human-reviewer",
        expected_revision=1,
    )


def _approved_plan_with_command_gate(temp_project: Path):
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="execution-smoke")
    created.plan.frontmatter["engineering"]["gates"] = [
        {
            "id": "unit-tests",
            "kind": "command",
            "blocking": True,
            "command": [sys.executable, "-c", "pass"],
        }
    ]
    created.plan.frontmatter["content_hash"] = canonical_plan_hash(created.plan)
    created.plan.path.write_text(
        f"---\n{yaml.safe_dump(created.plan.frontmatter, sort_keys=True, allow_unicode=True)}---\n{created.plan.body}\n",
        encoding="utf-8",
        newline="\n",
    )
    revised = revise_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        allow_stale=True,
        reason="Configure a trusted argv gate",
    )
    return approve_plan(
        temp_project,
        revised.plan.path.parent,
        revised.plan.id,
        approved_by="human-reviewer",
        expected_revision=2,
    )


def test_start_batch_records_state_revision(temp_project: Path) -> None:
    approved = _approved_plan(temp_project)

    started = start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
        actor="codex",
    )

    assert started.plan.status == "executing"
    assert started.plan.batches[0]["status"] == "in-progress"
    assert started.plan.tasks[0]["status"] == "in-progress"
    assert started.plan.frontmatter["revision"] == 3
    assert started.plan.frontmatter["revision_type"] == "state"
    assert started.snapshot_path.name == "0003.md"


def test_complete_batch_requires_gate_evidence(temp_project: Path) -> None:
    approved = _approved_plan(temp_project)
    started = start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
        actor="codex",
    )

    with pytest.raises(PlanError) as raised:
        complete_batch(
            temp_project,
            started.plan.path.parent,
            started.plan.id,
            batch="B1",
            expected_revision=3,
            actor="codex",
        )

    assert raised.value.code == "GATE_EVIDENCE_REQUIRED"
    unchanged = find_plan(started.plan.id, started.plan.path.parent, root=temp_project)
    assert unchanged.batches[0]["status"] == "in-progress"


def test_record_gate_result_and_complete_batch(temp_project: Path) -> None:
    approved = _approved_plan(temp_project)
    started = start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
        actor="codex",
    )
    test_path = temp_project / "tests" / "test_execution_smoke.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_first_task():\n    assert True\n", encoding="utf-8")

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

    result = recorded.plan.frontmatter["gate_results"][-1]
    assert result["gate_id"] == "unit-tests"
    assert result["outcome"] == "passed"
    assert result["plan_revision"] == 3
    assert result["gate_definition_hash"].startswith("sha256:")
    assert recorded.plan.frontmatter["revision"] == 4

    completed = complete_batch(
        temp_project,
        recorded.plan.path.parent,
        recorded.plan.id,
        batch="B1",
        expected_revision=4,
        actor="codex",
    )
    assert completed.plan.batches[0]["status"] == "passed"
    assert completed.plan.tasks[0]["status"] == "done"


def test_complete_batch_rejects_unbound_gate_result(temp_project: Path) -> None:
    approved = _approved_plan(temp_project)
    started = start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
        actor="codex",
    )
    test_path = temp_project / "tests" / "test_execution_smoke.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_first_task():\n    assert True\n", encoding="utf-8")
    record_gate_result(
        temp_project,
        started.plan.path.parent,
        started.plan.id,
        gate_id="unit-tests",
        outcome="passed",
        actor="trusted-runner",
        evidence_kind="runner",
        expected_revision=3,

        output_digest="sha256:fixed",
    )

    with pytest.raises(PlanError) as raised:
        complete_batch(
            temp_project,
            started.plan.path.parent,
            started.plan.id,
            batch="B1",
            expected_revision=4,
            actor="codex",
        )

    assert raised.value.code == "GATE_EVIDENCE_REQUIRED"


def test_complete_batch_rejects_missing_fingerprint(temp_project: Path) -> None:
    approved = _approved_plan(temp_project)
    started = start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
        actor="codex",
    )
    test_path = temp_project / "tests" / "test_execution_smoke.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_first_task():\n    assert True\n", encoding="utf-8")
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
    plan_path = recorded.plan.path
    frontmatter = dict(recorded.plan.frontmatter)
    frontmatter["gate_results"][-1].pop("input_fingerprint")
    frontmatter["content_hash"] = canonical_plan_hash(recorded.plan)
    plan_path.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=True, allow_unicode=True)}---\n{recorded.plan.body}\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(PlanError) as raised:
        complete_batch(
            temp_project,
            plan_path.parent,
            recorded.plan.id,
            batch="B1",
            expected_revision=4,
            actor="codex",
        )

    assert raised.value.code == "GATE_FINGERPRINT_REQUIRED"


def test_complete_batch_rejects_stale_fingerprint(temp_project: Path) -> None:
    approved = _approved_plan(temp_project)
    started = start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
        actor="codex",
    )
    test_path = temp_project / "tests" / "test_execution_smoke.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_first_task():\n    assert True\n", encoding="utf-8")
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
    test_path.write_text("def test_first_task():\n    assert True\n    assert 1 == 1\n", encoding="utf-8")

    with pytest.raises(PlanError) as raised:
        complete_batch(
            temp_project,
            recorded.plan.path.parent,
            recorded.plan.id,
            batch="B1",
            expected_revision=4,
            actor="codex",
        )

    assert raised.value.code == "GATE_EVIDENCE_STALE"


def test_task_completion_requires_test_contract(temp_project: Path) -> None:
    approved = _approved_plan(temp_project)
    started = start_batch(
        temp_project,
        approved.plan.path.parent,
        approved.plan.id,
        batch="B1",
        expected_revision=2,
        actor="codex",
    )
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

    with pytest.raises(PlanError) as raised:
        complete_batch(
            temp_project,
            recorded.plan.path.parent,
            recorded.plan.id,
            batch="B1",
            expected_revision=4,
            actor="codex",
        )

    assert raised.value.code == "TEST_CONTRACT_MISMATCH"


def test_run_gate_executes_configured_argv() -> None:
    outcome = run_gate(
        {
            "id": "unit-tests",
            "kind": "command",
            "command": [sys.executable, "-c", "pass"],
        }
    )

    assert outcome["outcome"] == "passed"
    assert outcome["exit_code"] == 0
    assert outcome["output_digest"].startswith("sha256:")


def test_cli_execution_surface(temp_project: Path) -> None:
    runner = CliRunner()
    approved = _approved_plan_with_command_gate(temp_project)
    plan_id = approved.plan.id
    test_path = temp_project / "tests" / "test_execution_smoke.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_first_task():\n    assert True\n", encoding="utf-8")

    started = runner.invoke(
        app,
        ["plan", "batch", "start", plan_id, "B1", str(temp_project), "--expected-revision", "3", "--json"],
    )
    assert started.exit_code == 0, started.output
    assert json.loads(started.output)["revision"] == 4

    gated = runner.invoke(
        app,
        ["plan", "gate", "run", plan_id, "B1", "unit-tests", str(temp_project), "--timeout", "10", "--json"],
    )
    assert gated.exit_code == 0, gated.output
    gated_payload = json.loads(gated.output)
    assert gated_payload["outcome"] == "passed"
    assert gated_payload["batch"] == "B1"

    completed = runner.invoke(
        app,
        ["plan", "batch", "complete", plan_id, "B1", str(temp_project), "--expected-revision", "5", "--json"],
    )
    assert completed.exit_code == 0, completed.output
    assert json.loads(completed.output)["status"] == "done"
