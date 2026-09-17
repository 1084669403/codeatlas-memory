"""Tests for the pure Markdown plan artifact contract (PR 1a, B1)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
from textwrap import dedent
from collections.abc import Iterator

import pytest
import yaml

from typer.testing import CliRunner

from codeatlas.plans import (
    PlanError,
    find_plan,
    lint_plan,
    lint_plans,
    parse_plan,
    parse_plan_text,
    plan_status,
    plan_view,
    render_plan_template,
)
from codeatlas.cli import app


@pytest.fixture
def temp_project(request) -> Iterator[Path]:
    root = Path.cwd() / ".test-tmp" / request.node.name
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    yield root
    shutil.rmtree(root)


def _frontmatter(**overrides: object) -> str:
    data = {
        "schema_version": 1,
        "id": "2026-09-17-parser-contract",
        "title": "Parser contract",
        "status": "draft",
        "created": "2026-09-17T00:00:00Z",
        "updated_at": "2026-09-17T00:00:00Z",
        "revision": 1,
        "content_hash": "pending",
        "revision_type": "semantic",
        "reapproval_required": False,
        "owner": "agent",
        "last_writer": "codex",
        "files": ["src/example.py"],
        "symbols": ["example.parse"],
        "context_pages": [],
        "evidence": [],
        "change_control": {"mode": "adaptive"},
        "engineering": {
            "profile": "product",
            "architecture_style": "none",
            "standards": [],
            "quality_gates": ["unit-tests"],
            "plain_language": False,
            "profile_revision": "v13-builtins",
        },
        "testing": {
            "approach": "test-with-change",
            "tests": [
                {
                    "test_id": "T-001",
                    "kind": "unit",
                    "behavior": "Parse a valid plan.",
                    "files": ["tests/test_plan_engine.py::test_parse_valid"],
                    "gate_id": "unit-tests",
                    "batch": "B1",
                    "task": 1,
                    "disposition": "implement",
                }
            ],
            "manual_checks": [],
        },
        "approval": None,
    }
    data.update(overrides)
    return yaml.safe_dump(data, sort_keys=True, allow_unicode=True)


def _body(validation: str = "unit-tests gate T-001") -> str:
    return dedent(
        f"""
        # Goal

        Parse and lint plan files.

        # Non-goals

        No CLI or persistence.

        # Tasks

        | # | Batch | Task | Depends on | Risk | Files | Symbols | Validation | Status |
        |---|---|---|---|---|---|---|---|---|
        | 1 | B1 | Add parser | none | medium | `src/example.py` | `example.parse` | {validation} | pending |

        # Validation

        Run the unit tests listed in the testing contract.

        # Testing strategy

        T-001 covers a valid plan. The contract is authoritative.

        # Execution notes

        Implement one batch at a time.

        # Engineering requirements

        Keep this module independent from CLI dependencies.

        # Quality gates

        unit-tests is blocking.

        # Batches

        | Batch | Purpose | Depends on | Status | Last validation |
        |---|---|---|---|---|
        | B1 | Parser contract | none | pending | none |
        """
    )


def _plan_text(**overrides: object) -> str:
    validation = overrides.pop("validation", "unit-tests gate T-001")
    return f"---\n{_frontmatter(**overrides)}---\n{_body(validation)}\n"


def _write_plan(root: Path, text: str, name: str = "plan.md") -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "example.py").write_text("def parse(): ...\n", encoding="utf-8")
    return path


def test_parse_valid_minimal_plan(temp_project: Path) -> None:
    path = _write_plan(temp_project, _plan_text())
    plan = parse_plan(path, root=temp_project)

    assert plan.frontmatter["id"] == "2026-09-17-parser-contract"
    assert plan.frontmatter["revision"] == 1
    assert plan.sections["goal"].strip() == "Parse and lint plan files."
    assert plan.tasks[0]["task"] == "Add parser"
    assert plan.tasks[0]["batch"] == "B1"
    assert plan.batches[0]["batch"] == "B1"


def test_parse_plan_with_utf8_bom(temp_project: Path) -> None:
    path = _write_plan(temp_project, _plan_text())
    raw = path.read_bytes()
    path.write_bytes(b"\xef\xbb\xbf" + raw)

    plan = parse_plan(path, root=temp_project)

    assert plan.id == "2026-09-17-parser-contract"
    assert lint_plan(path, root=temp_project) == []


def test_parse_invalid_frontmatter() -> None:
    with pytest.raises(PlanError) as exc_info:
        parse_plan_text("not a plan")

    assert exc_info.value.code == "PLAN_SCHEMA_INVALID"
    assert exc_info.value.message


def test_lint_resolves_referenced_files(temp_project: Path) -> None:
    text = _plan_text(files=["src/missing.py"])
    path = _write_plan(temp_project, text)
    issues = lint_plan(path, root=temp_project)
    codes = {issue.code for issue in issues}

    assert "PLAN_FILE_NOT_FOUND" in codes


def test_lint_rejects_duplicate_plan_ids(temp_project: Path) -> None:
    text = _plan_text()
    _write_plan(temp_project, text, "one.md")
    _write_plan(temp_project, text, "two.md")

    issues = lint_plans(temp_project, root=temp_project)
    codes = {issue.code for issue in issues}

    assert "PLAN_DUPLICATE_ID" in codes


def test_lint_rejects_vague_validation(temp_project: Path) -> None:
    path = _write_plan(temp_project, _plan_text(validation="test it"))
    issues = lint_plan(path, root=temp_project)

    assert any(issue.code == "PLAN_VAGUE_VALIDATION" for issue in issues)


def test_lint_rejects_invalid_gate_definitions(temp_project: Path) -> None:
    engineering = {
        "profile": "product",
        "architecture_style": "none",
        "standards": [],
        "quality_gates": ["unit-tests"],
        "gates": [
            {"id": "unit-tests", "kind": "command", "blocking": "yes", "command": "pytest -q"},
        ],
        "plain_language": False,
        "profile_revision": "v13-builtins",
    }
    path = _write_plan(temp_project, _plan_text(engineering=engineering))

    issues = lint_plan(path, root=temp_project)

    assert {issue.code for issue in issues} >= {
        "PLAN_SCHEMA_INVALID",
        "GATE_COMMAND_INVALID",
    }


def test_lint_rejects_task_and_batch_state_conflict(temp_project: Path) -> None:
    text = _plan_text().replace(
        "| B1 | Parser contract | none | pending | none |",
        "| B1 | Parser contract | none | passed | none |",
    )
    path = _write_plan(temp_project, text)

    issues = lint_plan(path, root=temp_project)

    assert any(issue.code == "PLAN_STATE_CONFLICT" for issue in issues)


def test_lint_returns_stable_errors(temp_project: Path) -> None:
    path = _write_plan(temp_project, _plan_text(files=["src/missing.py"]))
    issues = lint_plan(path, root=temp_project)

    assert issues
    assert all(issue.code == issue.code.upper() for issue in issues)
    assert all(issue.message for issue in issues)


def test_status_groups_and_warns(temp_project: Path) -> None:
    _write_plan(temp_project, _plan_text(), "draft.md")
    _write_plan(temp_project, _plan_text(status="done"), "done.md")
    (temp_project / "broken.md").write_text("not a plan", encoding="utf-8")

    payload = plan_status(temp_project, root=temp_project)

    assert payload["total"] == 2
    groups = {group["status"]: group["plans"] for group in payload["groups"]}
    assert {plan["id"] for plan in groups["draft"]} == {"2026-09-17-parser-contract"}
    assert {plan["id"] for plan in groups["done"]} == {"2026-09-17-parser-contract"}
    # A plans directory may retain non-frontmatter legacy documents; doctor
    # reports them separately as non-fatal warnings.
    assert payload["warnings"] == []


def test_cli_new_show_and_lint(temp_project: Path) -> None:
    runner = CliRunner()

    created = runner.invoke(
        app,
        ["plan", "new", "smoke-plan", str(temp_project), "--json"],
    )
    assert created.exit_code == 0, created.output
    created_payload = json.loads(created.output)
    plan_id = created_payload["id"]

    found = find_plan(plan_id, temp_project / "docs" / "plans", root=temp_project)
    summary_view = plan_view(found, view="summary")
    full_view = plan_view(found, view="full")
    assert summary_view["status"] == "draft"
    assert summary_view["next_batch"] == "B1"
    assert "tasks" in full_view

    shown = runner.invoke(
        app,
        ["plan", "show", plan_id, str(temp_project), "--view", "full", "--json"],
    )
    assert shown.exit_code == 0, shown.output
    shown_payload = json.loads(shown.output)
    assert shown_payload["id"] == plan_id
    assert shown_payload["tasks"][0]["batch"] == "B1"

    linted = runner.invoke(app, ["plan", "lint", str(temp_project), "--json"])
    assert linted.exit_code == 0, linted.output
    assert json.loads(linted.output)["ok"] is True


def test_template_fixture_lints_clean() -> None:
    template = Path(__file__).resolve().parents[1] / "docs" / "templates" / "plan-template.md"

    assert template.is_file()
    assert lint_plan(template, root=template.parents[2]) == []



