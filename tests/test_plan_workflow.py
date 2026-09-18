"""Tests for the durable Markdown plan workflow (PR 1b)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from typer.testing import CliRunner

from codeatlas.cli import app
from codeatlas.plans import lint_plan, parse_plan
from codeatlas.plans import PlanError
from codeatlas.plan_workflow import (
    approve_plan,
    canonical_plan_hash,
    complete_batch,
    create_plan,
    diff_plan,
    plan_projection_path,
    record_gate_result,
    reapprove_plan,
    revise_plan,
    start_batch,
    mark_batch_stale,
    reopen_batch,
    write_plan_projection,
)
from codeatlas.plans import plan_view


def test_create_plan_hashes_and_snapshots(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="auth-refactor",
    )

    assert created.plan.frontmatter["content_hash"] == canonical_plan_hash(created.plan)
    assert created.snapshot_path.is_file()
    assert created.snapshot_path.read_text(encoding="utf-8") == created.plan.path.read_text(encoding="utf-8")
    assert created.event_path.is_file()
    assert lint_plan(created.plan.path, root=temp_project) == []


def test_approve_records_durable_approval(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="auth-refactor",
    )

    approved = approve_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        approved_by="human-reviewer",
        basis="conversation",
        expected_revision=1,
    )

    assert approved.plan.status == "approved"
    assert approved.plan.frontmatter["revision"] == 2
    assert approved.plan.frontmatter["reapproval_required"] is False
    assert approved.plan.frontmatter["approval"]["decision"] == "approved"
    assert approved.plan.frontmatter["approval"]["approved_by"] == "human-reviewer"
    assert approved.plan.frontmatter["approval"]["profile_hash"].startswith("sha256:")
    assert approved.plan.frontmatter["approval"]["gate_set_hash"].startswith("sha256:")
    assert approved.plan.frontmatter["content_hash"] == canonical_plan_hash(approved.plan)
    assert approved.snapshot_path.name == "0002.md"
    assert lint_plan(approved.plan.path, root=temp_project) == []


def test_approve_rejects_pending_content_hash(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="pending-hash",
    )
    created.plan.frontmatter["content_hash"] = "pending"
    plan_path = created.plan.path
    plan_path.write_text(
        f"---\n{yaml.safe_dump(created.plan.frontmatter, sort_keys=True, allow_unicode=True)}---\n{created.plan.body}\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(PlanError) as raised:
        approve_plan(
            temp_project,
            plan_path.parent,
            created.plan.id,
            approved_by="human-reviewer",
            expected_revision=1,
        )

    assert raised.value.code == "PLAN_CONTENT_HASH_PENDING"


def test_revise_flags_semantic_reapproval(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="auth-refactor",
    )
    approved = approve_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        approved_by="human-reviewer",
        basis="conversation",
        expected_revision=1,
    )
    plan_path = approved.plan.path
    text = plan_path.read_text(encoding="utf-8")
    plan_path.write_text(
        text.replace("# Goal\n\n", "# Goal\n\nAuth refactor with refresh tokens.\n"),
        encoding="utf-8",
    )

    revised = revise_plan(
        temp_project,
        plan_path.parent,
        approved.plan.id,
        expected_revision=2,
        allow_stale=True,
        reason="Scope now includes refresh tokens",
    )

    assert revised.plan.status == "approved"
    assert revised.plan.frontmatter["revision"] == 3
    assert revised.plan.frontmatter["revision_type"] == "semantic"
    assert revised.plan.frontmatter["reapproval_required"] is True
    assert revised.plan.frontmatter["content_hash"] == canonical_plan_hash(revised.plan)
    assert revised.snapshot_path.name == "0003.md"
    assert lint_plan(revised.plan.path, root=temp_project) == []


def test_reapprove_clears_semantic_revision_flag(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="reapproval-smoke",
    )
    approved = approve_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        approved_by="human-reviewer",
        expected_revision=1,
    )
    plan_path = approved.plan.path
    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace(
            "# Goal\n\n",
            "# Goal\n\nScope includes token refresh.\n",
        ),
        encoding="utf-8",
    )
    revised = revise_plan(
        temp_project,
        plan_path.parent,
        approved.plan.id,
        expected_revision=2,
        allow_stale=True,
        reason="Scope changed",
    )

    reapproved = reapprove_plan(
        temp_project,
        plan_path.parent,
        approved.plan.id,
        approved_by="human-reviewer",
        basis="review-doc",
        expected_revision=3,
    )

    assert reapproved.plan.status == "approved"
    assert reapproved.plan.frontmatter["reapproval_required"] is False
    assert reapproved.plan.frontmatter["revision"] == 4
    assert reapproved.plan.frontmatter["approval"]["decision"] == "reapproved"
    assert reapproved.snapshot_path.name == "0004.md"
    assert lint_plan(reapproved.plan.path, root=temp_project) == []


def test_reapprove_rejects_plan_without_flag(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="no-reapproval-smoke",
    )
    approved = approve_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        approved_by="human-reviewer",
        expected_revision=1,
    )

    with pytest.raises(PlanError) as raised:
        reapprove_plan(
            temp_project,
            approved.plan.path.parent,
            approved.plan.id,
            approved_by="human-reviewer",
            expected_revision=2,
        )

    assert raised.value.code == "PLAN_REAPPROVAL_NOT_REQUIRED"


def _completed_plan(temp_project: Path, *, slug: str = "reopen-smoke"):
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug=slug)
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
    test_path = temp_project / "tests" / f"test_{slug.replace('-', '_')}.py"
    test_path.parent.mkdir(exist_ok=True)
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
    completed = complete_batch(
        temp_project,
        recorded.plan.path.parent,
        recorded.plan.id,
        batch="B1",
        expected_revision=4,
    )
    return completed


def _completed_stale_plan(temp_project: Path):
    completed = _completed_plan(temp_project)
    return mark_batch_stale(
        temp_project,
        completed.plan.path.parent,
        completed.plan.id,
        batch="B1",
        reason="Post-completion correction changed batch inputs",
        expected_revision=5,
    )


def test_reopen_requires_stale_batch_in_done_plan(temp_project: Path) -> None:
    stale = _completed_stale_plan(temp_project)

    with pytest.raises(PlanError) as reason_error:
        reopen_batch(
            temp_project,
            stale.plan.path.parent,
            stale.plan.id,
            batch="B1",
            reason="   ",
            expected_revision=6,
        )
    assert reason_error.value.code == "PLAN_REOPEN_REASON_REQUIRED"

    passed = _completed_plan(temp_project, slug="reopen-passed")
    with pytest.raises(PlanError) as batch_error:
        reopen_batch(
            temp_project,
            passed.plan.path.parent,
            passed.plan.id,
            batch="B1",
            reason="Batch is not stale",
            expected_revision=5,
        )
    assert batch_error.value.code == "INVALID_TRANSITION"

    plan_path = stale.plan.path
    frontmatter = dict(stale.plan.frontmatter)
    frontmatter["status"] = "executing"
    frontmatter["content_hash"] = "pending"
    plan_path.write_text(
        f"---\n{yaml.safe_dump(frontmatter, sort_keys=True, allow_unicode=True)}---\n{stale.plan.body}\n",
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(PlanError) as status_error:
        reopen_batch(
            temp_project,
            plan_path.parent,
            stale.plan.id,
            batch="B1",
            reason="Plan is not done",
        )
    assert status_error.value.code == "PLAN_CONTENT_HASH_STALE"


def test_reopen_changes_stale_batch_to_blocked(temp_project: Path) -> None:
    stale = _completed_stale_plan(temp_project)

    reopened = reopen_batch(
        temp_project,
        stale.plan.path.parent,
        stale.plan.id,
        batch="B1",
        reason="Refresh gate evidence after post-completion correction",
        expected_revision=6,
    )

    assert reopened.plan.status == "blocked"
    assert reopened.plan.batches[0]["status"] == "blocked"
    assert reopened.plan.tasks[0]["status"] == "blocked"
    assert reopened.plan.frontmatter["revision"] == 7
    assert reopened.plan.frontmatter["revision_type"] == "state"
    assert reopened.plan.frontmatter["stale_evidence"][-1]["reason"] == (
        "Post-completion correction changed batch inputs"
    )
    assert reopened.snapshot_path.name == "0007.md"
    assert "batch_reopened" in reopened.event_path.read_text(encoding="utf-8")
    assert lint_plan(reopened.plan.path, root=temp_project) == []


def test_reopened_batch_can_start_for_fresh_evidence(temp_project: Path) -> None:
    stale = _completed_stale_plan(temp_project)
    reopened = reopen_batch(
        temp_project,
        stale.plan.path.parent,
        stale.plan.id,
        batch="B1",
        reason="Refresh gate evidence",
        expected_revision=6,
    )

    restarted = start_batch(
        temp_project,
        reopened.plan.path.parent,
        reopened.plan.id,
        batch="B1",
        expected_revision=7,
    )
    assert restarted.plan.status == "executing"
    assert restarted.plan.batches[0]["status"] == "in-progress"
    assert restarted.plan.tasks[0]["status"] == "in-progress"
    assert restarted.plan.frontmatter["batch_started_revision"] == 7

    recorded = record_gate_result(
        temp_project,
        restarted.plan.path.parent,
        restarted.plan.id,
        gate_id="unit-tests",
        outcome="passed",
        actor="trusted-runner",
        evidence_kind="runner",
        batch="B1",
        expected_revision=8,
        output_digest="sha256:fixed",
    )
    completed = complete_batch(
        temp_project,
        recorded.plan.path.parent,
        recorded.plan.id,
        batch="B1",
        expected_revision=9,
    )
    assert completed.plan.status == "done"
    assert completed.plan.batches[0]["status"] == "passed"
    assert completed.plan.tasks[0]["status"] == "done"


def test_cli_reopens_stale_batch_for_revalidation(temp_project: Path) -> None:
    stale = _completed_stale_plan(temp_project)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "plan", "batch", "reopen", stale.plan.id, "B1", str(temp_project),
            "--reason", "Refresh gate evidence after post-completion correction",
            "--expected-revision", "6",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["id"] == stale.plan.id
    assert payload["batch"] == "B1"
    assert payload["status"] == "blocked"
    assert payload["revision"] == 7
    assert payload["snapshot_path"] == f"docs/plans/revisions/{stale.plan.id}/0007.md"


def test_diff_classifies_revisions(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="auth-refactor",
    )
    approved = approve_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        approved_by="human-reviewer",
        basis="conversation",
        expected_revision=1,
    )

    plan_path = approved.plan.path
    semantic_text = plan_path.read_text(encoding="utf-8")
    plan_path.write_text(
        semantic_text.replace("# Goal\n\n", "# Goal\n\nAuth refactor with refresh tokens.\n"),
        encoding="utf-8",
    )
    semantic = revise_plan(
        temp_project,
        plan_path.parent,
        approved.plan.id,
        expected_revision=2,
        allow_stale=True,
        reason="Scope changed",
    )
    semantic_diff = diff_plan(
        temp_project,
        plan_path.parent,
        approved.plan.id,
        from_revision=2,
        to_revision=3,
    )
    assert semantic_diff["semantic"] is True
    assert semantic_diff["state"] is False
    assert semantic_diff["formatting"] is False

    state_text = semantic.plan.path.read_text(encoding="utf-8")
    semantic.plan.path.write_text(
        state_text.replace("| unit-tests gate | pending |", "| unit-tests gate | in-progress |"),
        encoding="utf-8",
    )
    state = revise_plan(
        temp_project,
        plan_path.parent,
        approved.plan.id,
        expected_revision=3,
        allow_stale=True,
        writer="human-reviewer",
    )
    state_diff = diff_plan(
        temp_project,
        plan_path.parent,
        approved.plan.id,
        from_revision=3,
        to_revision=4,
    )
    assert state_diff["semantic"] is False
    assert state_diff["state"] is True
    assert state_diff["formatting"] is False


def test_bounded_views(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="auth-refactor",
    )

    execution = plan_view(created.plan, view="execution")
    engineering = plan_view(created.plan, view="engineering")
    evidence = plan_view(created.plan, view="evidence")

    assert execution["next_batch"] == "B1"
    assert execution["tasks"][0]["batch"] == "B1"
    assert "testing" in execution
    assert engineering["profile"] == "product"
    assert engineering["quality_gates"] == ["unit-tests"]
    assert "engineering_requirements" in engineering
    assert evidence["evidence"] == []
    for view in (execution, engineering, evidence):
        assert "body" not in view
        assert "sections" not in view


def test_projection_is_rebuildable(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="auth-refactor",
    )
    projection_path = plan_projection_path(temp_project, created.plan.id)
    projection_path.unlink(missing_ok=True)

    write_plan_projection(temp_project, created.plan)

    assert projection_path.is_file()
    payload = json.loads(projection_path.read_text(encoding="utf-8"))
    assert payload["id"] == created.plan.id
    assert payload["revision"] == 1
    assert payload["content_hash"] == canonical_plan_hash(created.plan)
    assert payload["source_path"].startswith("docs/plans/")



def test_revise_can_bootstrap_legacy_plan(temp_project: Path) -> None:
    created = create_plan(
        temp_project,
        temp_project / "docs" / "plans",
        slug="legacy-bootstrap",
    )
    workflow_dir = temp_project / "docs" / "plans" / "revisions" / created.plan.id
    for path in workflow_dir.iterdir():
        path.unlink()

    revised = revise_plan(
        temp_project,
        created.plan.path.parent,
        created.plan.id,
        bootstrap=True,
        reason="Migrate a pre-workflow plan",
    )

    assert (workflow_dir / "0001.md").is_file()
    assert revised.snapshot_path.name == "0002.md"
    assert revised.plan.frontmatter["revision"] == 2

def test_canonical_hash_accepts_yaml_date_objects(temp_project: Path) -> None:
    created = create_plan(temp_project, temp_project / "docs" / "plans", slug="date-hash")
    created.plan.frontmatter["created"] = "2026-09-17T00:00:00Z"
    created.plan.frontmatter["updated_at"] = "2026-09-17T00:00:00Z"

    assert canonical_plan_hash(created.plan).startswith("sha256:")


def test_cli_workflow(temp_project: Path) -> None:
    runner = CliRunner()

    created = runner.invoke(app, ["plan", "new", "auth-refactor", str(temp_project), "--json"])
    assert created.exit_code == 0, created.output
    created_payload = json.loads(created.output)
    plan_id = created_payload["id"]
    plan_path = temp_project / created_payload["path"]
    assert created_payload["revision"] == 1
    assert created_payload["snapshot_path"].startswith("docs/plans/revisions/")

    approved = runner.invoke(
        app,
        [
            "plan", "approve", plan_id, str(temp_project),
            "--approved-by", "human-reviewer",
            "--basis", "conversation",
            "--expected-revision", "1",
            "--json",
        ],
    )
    assert approved.exit_code == 0, approved.output
    assert json.loads(approved.output)["revision"] == 2

    plan_path.write_text(
        plan_path.read_text(encoding="utf-8").replace("# Goal\n\n", "# Goal\n\nAuth refactor with refresh tokens.\n"),
        encoding="utf-8",
    )
    revised = runner.invoke(
        app,
        [
            "plan", "revise", plan_id, str(temp_project),
            "--expected-revision", "2",
            "--allow-stale",
            "--reason", "Scope changed",
            "--json",
        ],
    )
    assert revised.exit_code == 0, revised.output
    revised_payload = json.loads(revised.output)
    assert revised_payload["revision"] == 3
    assert revised_payload["reapproval_required"] is True

    diffed = runner.invoke(
        app,
        [
            "plan", "diff", plan_id, str(temp_project),
            "--from-revision", "2",
            "--to-revision", "3",
            "--json",
        ],
    )
    assert diffed.exit_code == 0, diffed.output
    assert json.loads(diffed.output)["semantic"] is True

    reapproved = runner.invoke(
        app,
        [
            "plan", "reapprove", plan_id, str(temp_project),
            "--approved-by", "human-reviewer",
            "--basis", "review-doc",
            "--expected-revision", "3",
            "--json",
        ],
    )
    assert reapproved.exit_code == 0, reapproved.output
    reapproved_payload = json.loads(reapproved.output)
    assert reapproved_payload["status"] == "approved"
    assert reapproved_payload["reapproval_required"] is False
    assert reapproved_payload["revision"] == 4

    shown = runner.invoke(app, ["plan", "show", plan_id, str(temp_project), "--view", "execution", "--json"])
    assert shown.exit_code == 0, shown.output
    execution = json.loads(shown.output)
    assert execution["next_batch"] == "B1"
    assert "body" not in execution
