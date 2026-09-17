"""Pure Markdown plan artifact parsing, validation, and template rendering.

This module is intentionally independent from Typer, Rich, SQLite, and MCP so
the plan contract can be reused by the CLI, tests, and future agent surfaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


PLAN_SCHEMA_VERSION = 1
PLAN_MAX_BYTES = 1_048_576
PLAN_STATUSES = {"draft", "approved", "executing", "blocked", "done", "cancelled"}
TASK_STATUSES = {"pending", "in-progress", "blocked", "done", "skipped"}
TASK_RISKS = {"low", "medium", "high"}
BATCH_STATUSES = {"pending", "in-progress", "validating", "passed", "failed", "blocked", "skipped", "stale"}
GATE_KINDS = {"command", "review", "manual"}
GATE_OUTCOMES = {"passed", "failed", "not-run"}
GATE_EVIDENCE_KINDS = {"runner", "external", "review"}
ENGINEERING_PROFILES = {"prototype", "product", "production"}
ARCHITECTURE_STYLES = {"none", "layered", "modular-monolith", "event-driven", "plugin"}
REVISION_TYPES = {"semantic", "state"}
TEST_DISPOSITIONS = {"implement", "reuse", "omit"}

_REQUIRED_FRONTMATTER = {
    "schema_version",
    "id",
    "title",
    "status",
    "created",
    "updated_at",
    "revision",
    "content_hash",
    "revision_type",
    "reapproval_required",
    "owner",
    "last_writer",
    "files",
    "symbols",
    "context_pages",
    "evidence",
    "change_control",
    "engineering",
    "testing",
    "approval",
}

_REQUIRED_BODY_SECTIONS = {
    "goal",
    "non-goals",
    "tasks",
    "validation",
    "testing strategy",
    "execution notes",
    "engineering requirements",
    "quality gates",
}

_VAGUE_VALIDATIONS = {
    "test it",
    "test",
    "tests",
    "verify",
    "verify it",
    "verify it works",
    "it works",
    "manual test",
}

_BACKTICK_VALUE = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


class PlanError(Exception):
    """A deterministic, machine-readable plan parsing error."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.path = path
        self.details = details or {}


@dataclass(frozen=True)
class LintIssue:
    """One stable, actionable lint finding."""

    code: str
    message: str
    field: str | None = None
    path: str | None = None


@dataclass
class Plan:
    """A parsed plan file with normalized Markdown structure."""

    path: Path
    source_path: str
    frontmatter: dict[str, Any]
    body: str
    sections: dict[str, str]
    tasks: list[dict[str, Any]]
    batches: list[dict[str, Any]]
    warnings: list[LintIssue] = field(default_factory=list)

    @property
    def id(self) -> str:
        return str(self.frontmatter["id"])

    @property
    def status(self) -> str:
        return str(self.frontmatter["status"])

    @property
    def engineering_profile(self) -> str:
        engineering = self.frontmatter.get("engineering", {})
        return str(engineering.get("profile", "product"))


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or "plan"


def _normalize_repo_path(value: str) -> str:
    """Normalize one repository-relative path to POSIX form."""
    if not isinstance(value, str) or not value.strip():
        raise PlanError("PLAN_SCHEMA_INVALID", "Paths must be non-empty strings.", field="files")
    raw = value.strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or raw.startswith("/") or len(raw) > 1 and raw[1] == ":":
        raise PlanError("PLAN_SCHEMA_INVALID", "Paths must be repository-relative.", field="files")
    if any(part in {"..", ""} for part in path.parts):
        raise PlanError("PLAN_SCHEMA_INVALID", "Paths must not escape the project root.", field="files")
    return path.as_posix()


def _as_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise PlanError("PLAN_SCHEMA_INVALID", f"{field_name} must be a list.", field=field_name)
    return value


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PlanError("PLAN_SCHEMA_INVALID", "Plan must start with YAML frontmatter.", field="frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise PlanError("PLAN_SCHEMA_INVALID", "YAML frontmatter is not closed.", field="frontmatter") from exc
    raw_yaml = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise PlanError("PLAN_SCHEMA_INVALID", f"Invalid YAML frontmatter: {exc}", field="frontmatter") from exc
    if not isinstance(data, dict):
        raise PlanError("PLAN_SCHEMA_INVALID", "YAML frontmatter must be a mapping.", field="frontmatter")
    return data, "\n".join(lines[end + 1 :])


def _extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current: str | None = None
    for line in body.splitlines():
        match = _HEADING.match(line)
        if match:
            current = match.group(1).strip().casefold()
            sections.setdefault(current, "")
            continue
        if current is not None:
            sections[current] += line + "\n"
    return {name: value.strip() for name, value in sections.items()}


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells)


def _parse_table(section: str) -> list[dict[str, str]]:
    rows = [line for line in section.splitlines() if line.strip().startswith("|")]
    if len(rows) < 2:
        return []
    headers = [cell.casefold() for cell in _split_table_row(rows[0])]
    parsed: list[dict[str, str]] = []
    for line in rows[1:]:
        if _is_table_separator(line):
            continue
        cells = _split_table_row(line)
        if len(cells) != len(headers):
            continue
        parsed.append(dict(zip(headers, cells, strict=True)))
    return parsed


def _referenced_paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [
            item.strip().strip("`")
            for item in value.split(",")
            if item.strip() and item.strip().casefold() not in {"none", "n/a", "-", "todo"}
        ]
    if isinstance(value, list):
        return [str(item).strip().strip("`") for item in value if str(item).strip()]
    return []


def _parse_plan_document(text: str, path: Path) -> Plan:
    frontmatter, body = _split_frontmatter(text)
    sections = _extract_sections(body)
    warnings: list[LintIssue] = []

    tasks_raw = _parse_table(sections.get("tasks", ""))
    tasks: list[dict[str, Any]] = []
    if not tasks_raw:
        warnings.append(LintIssue("PLAN_TASKS_MISSING", "The Tasks section must contain a valid task table.", path=path.as_posix()))
    for row in tasks_raw:
        task: dict[str, Any] = dict(row)
        task["files"] = _referenced_paths(row.get("files", ""))
        task["symbols"] = _referenced_paths(row.get("symbols", ""))
        try:
            task["number"] = int(row.get("#", "0"))
        except ValueError:
            task["number"] = 0
            warnings.append(LintIssue("PLAN_SCHEMA_INVALID", f"Task number is not an integer: {row.get('#', '')}", field="tasks"))
        tasks.append(task)

    batches = _parse_table(sections.get("batches", ""))
    return Plan(
        path=path,
        source_path=path.as_posix(),
        frontmatter=frontmatter,
        body=body,
        sections=sections,
        tasks=tasks,
        batches=batches,
        warnings=warnings,
    )


def parse_plan_text(text: str, *, source_path: str | Path = "plan.md") -> Plan:
    """Parse plan text without touching the filesystem."""
    if len(text.encode("utf-8")) > PLAN_MAX_BYTES:
        raise PlanError("PLAN_TOO_LARGE", f"Plan exceeds {PLAN_MAX_BYTES} bytes.", path=str(source_path))
    path = Path(source_path)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return _parse_plan_document(normalized, path)


def parse_plan(path: str | Path, *, root: str | Path = ".") -> Plan:
    """Read and parse one plan file."""
    plan_path = Path(path).resolve()
    root_path = Path(root).resolve()
    if not plan_path.is_file():
        raise PlanError("PLAN_NOT_FOUND", f"Plan not found: {plan_path}", path=plan_path.as_posix())
    try:
        source_path = plan_path.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise PlanError(
            "PLAN_OUTSIDE_ROOT",
            f"Plan is outside the project root: {plan_path}",
            path=plan_path.as_posix(),
        ) from exc
    size = plan_path.stat().st_size
    if size > PLAN_MAX_BYTES:
        raise PlanError("PLAN_TOO_LARGE", f"Plan exceeds {PLAN_MAX_BYTES} bytes.", path=plan_path.as_posix())
    try:
        text = plan_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise PlanError("PLAN_READ_FAILED", f"Could not read plan: {exc}", path=plan_path.as_posix()) from exc
    plan = parse_plan_text(text, source_path=source_path)
    plan.path = plan_path
    plan.source_path = source_path
    return plan


def _issue(code: str, message: str, *, field: str | None = None, path: str | None = None) -> LintIssue:
    return LintIssue(code=code, message=message, field=field, path=path)


def _validate_frontmatter(plan: Plan, issues: list[LintIssue]) -> None:
    data = plan.frontmatter
    missing = sorted(_REQUIRED_FRONTMATTER - data.keys())
    if missing:
        issues.append(_issue("PLAN_SCHEMA_INVALID", f"Missing frontmatter fields: {', '.join(missing)}", field="frontmatter", path=plan.source_path))
        return

    if data["schema_version"] != PLAN_SCHEMA_VERSION:
        issues.append(_issue("PLAN_SCHEMA_INVALID", f"schema_version must be {PLAN_SCHEMA_VERSION}.", field="schema_version", path=plan.source_path))
    if not isinstance(data["id"], str) or not data["id"].strip():
        issues.append(_issue("PLAN_SCHEMA_INVALID", "id must be a non-empty string.", field="id", path=plan.source_path))
    if data["status"] not in PLAN_STATUSES:
        issues.append(_issue("PLAN_SCHEMA_INVALID", f"Invalid plan status: {data['status']}", field="status", path=plan.source_path))
    if not isinstance(data["revision"], int) or data["revision"] < 1:
        issues.append(_issue("PLAN_SCHEMA_INVALID", "revision must be a positive integer.", field="revision", path=plan.source_path))
    if not isinstance(data["content_hash"], str) or not data["content_hash"].strip():
        issues.append(_issue("PLAN_SCHEMA_INVALID", "content_hash must be a non-empty string.", field="content_hash", path=plan.source_path))
    if data["revision_type"] not in REVISION_TYPES:
        issues.append(_issue("PLAN_SCHEMA_INVALID", f"Invalid revision_type: {data['revision_type']}", field="revision_type", path=plan.source_path))
    if not isinstance(data["reapproval_required"], bool):
        issues.append(_issue("PLAN_SCHEMA_INVALID", "reapproval_required must be boolean.", field="reapproval_required", path=plan.source_path))

    for field_name in ("files", "symbols", "context_pages", "evidence"):
        try:
            _as_list(data[field_name], field_name)
        except PlanError as exc:
            issues.append(_issue(exc.code, exc.message, field=exc.field, path=plan.source_path))

    change_control = data["change_control"]
    if not isinstance(change_control, dict):
        issues.append(_issue("PLAN_SCHEMA_INVALID", "change_control must be a mapping.", field="change_control", path=plan.source_path))
    elif change_control.get("mode") not in {"adaptive", "strict"}:
        issues.append(_issue("PLAN_SCHEMA_INVALID", "change_control.mode must be adaptive or strict.", field="change_control.mode", path=plan.source_path))

    engineering = data["engineering"]
    if not isinstance(engineering, dict):
        issues.append(_issue("PLAN_SCHEMA_INVALID", "engineering must be a mapping.", field="engineering", path=plan.source_path))
    else:
        if engineering.get("profile") not in ENGINEERING_PROFILES:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Invalid engineering profile: {engineering.get('profile')}", field="engineering.profile", path=plan.source_path))
        if engineering.get("architecture_style") not in ARCHITECTURE_STYLES:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Invalid architecture_style: {engineering.get('architecture_style')}", field="engineering.architecture_style", path=plan.source_path))
        for key in ("standards", "quality_gates"):
            try:
                _as_list(engineering.get(key), f"engineering.{key}")
            except PlanError as exc:
                issues.append(_issue(exc.code, exc.message, field=exc.field, path=plan.source_path))
        if engineering.get("gates") is not None:
            _validate_gate_definitions(engineering.get("gates"), issues, plan.source_path)
        if not isinstance(engineering.get("plain_language"), bool):
            issues.append(_issue("PLAN_SCHEMA_INVALID", "engineering.plain_language must be boolean.", field="engineering.plain_language", path=plan.source_path))

    testing = data["testing"]
    if not isinstance(testing, dict):
        issues.append(_issue("PLAN_SCHEMA_INVALID", "testing must be a mapping.", field="testing", path=plan.source_path))
    else:
        if testing.get("approach") not in {"test-with-change", "reproduction-first", "test-after-with-reason"}:
            issues.append(_issue("PLAN_SCHEMA_INVALID", "Invalid testing.approach.", field="testing.approach", path=plan.source_path))
        for key in ("tests", "manual_checks"):
            try:
                _as_list(testing.get(key), f"testing.{key}")
            except PlanError as exc:
                issues.append(_issue(exc.code, exc.message, field=exc.field, path=plan.source_path))


def _validate_sections(plan: Plan, issues: list[LintIssue]) -> None:
    for name in sorted(_REQUIRED_BODY_SECTIONS):
        if name not in plan.sections or not plan.sections[name].strip():
            issues.append(_issue("PLAN_SECTION_MISSING", f"Missing required section: {name.title()}", field=f"sections.{name}", path=plan.source_path))

    profile = plan.engineering_profile
    if profile in {"product", "production"} and not plan.sections.get("testing strategy", "").strip():
        issues.append(_issue("PLAN_TESTING_STRATEGY_MISSING", "Product and production plans require a Testing strategy section.", path=plan.source_path))


def _validate_references(plan: Plan, root: Path, issues: list[LintIssue]) -> None:
    root_resolved = root.resolve()
    for value in _as_list(plan.frontmatter.get("files", []), "files"):
        try:
            normalized = _normalize_repo_path(value)
        except PlanError as exc:
            issues.append(_issue(exc.code, exc.message, field=exc.field, path=plan.source_path))
            continue
        target = (root_resolved / normalized).resolve()
        if not target.is_file() or not target.is_relative_to(root_resolved):
            issues.append(_issue("PLAN_FILE_NOT_FOUND", f"Referenced file does not exist: {normalized}", field=f"files[{value}]", path=plan.source_path))

    for task in plan.tasks:
        for value in task.get("files", []):
            try:
                normalized = _normalize_repo_path(value)
            except PlanError as exc:
                issues.append(_issue(exc.code, exc.message, field=f"tasks[{task.get('number')}]"))
                continue
            target = (root_resolved / normalized).resolve()
            if not target.is_file() or not target.is_relative_to(root_resolved):
                issues.append(_issue("PLAN_FILE_NOT_FOUND", f"Task file does not exist: {normalized}", field=f"tasks[{task.get('number')}].files", path=plan.source_path))


def _validate_tasks(plan: Plan, issues: list[LintIssue]) -> None:
    seen_numbers: set[int] = set()
    batch_ids = {str(row.get("batch", "")).strip() for row in plan.batches if row.get("batch")}
    for task in plan.tasks:
        number = task.get("number", 0)
        if number in seen_numbers:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Duplicate task number: {number}", field="tasks.#", path=plan.source_path))
        seen_numbers.add(number)
        if task.get("status") not in TASK_STATUSES:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Invalid task status: {task.get('status')}", field=f"tasks[{number}].status", path=plan.source_path))
        if task.get("risk") not in TASK_RISKS:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Invalid task risk: {task.get('risk')}", field=f"tasks[{number}].risk", path=plan.source_path))
        batch_id = str(task.get("batch", "")).strip()
        if not batch_id:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Task {number} is missing a batch ID.", field=f"tasks[{number}].batch", path=plan.source_path))
        elif plan.batches and batch_id not in batch_ids:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Task {number} references unknown batch: {batch_id}", field=f"tasks[{number}].batch", path=plan.source_path))

        validation = str(task.get("validation", "")).strip()
        normalized = re.sub(r"[^a-z0-9 ]+", " ", validation.casefold()).strip()
        if not validation or normalized in _VAGUE_VALIDATIONS:
            issues.append(_issue("PLAN_VAGUE_VALIDATION", f"Task {number} validation is too vague.", field=f"tasks[{number}].validation", path=plan.source_path))
        elif "gate" not in normalized and "manual" not in normalized and "artifact" not in normalized:
            issues.append(_issue("PLAN_VAGUE_VALIDATION", f"Task {number} must name a gate or manual-check artifact.", field=f"tasks[{number}].validation", path=plan.source_path))


def _validate_batches(plan: Plan, issues: list[LintIssue]) -> None:
    for row in plan.batches:
        batch_id = str(row.get("batch", "")).strip()
        if not batch_id:
            issues.append(_issue("PLAN_SCHEMA_INVALID", "A batch row is missing a batch ID.", field="batches.batch", path=plan.source_path))
        status = str(row.get("status", "")).strip()
        if status and status not in BATCH_STATUSES:
            issues.append(_issue("BATCH_STATE_INVALID", f"Invalid batch status: {status}", field=f"batches[{batch_id}].status", path=plan.source_path))


def _validate_testing_contract(plan: Plan, issues: list[LintIssue]) -> None:
    testing = plan.frontmatter.get("testing", {})
    if not isinstance(testing, dict):
        return
    tests = _as_list(testing.get("tests", []), "testing.tests")
    profile = plan.engineering_profile
    if profile in {"product", "production"} and not tests and not testing.get("manual_checks"):
        issues.append(_issue("PLAN_TESTING_STRATEGY_MISSING", "Product and production plans need structured tests or manual checks.", field="testing.tests", path=plan.source_path))

    seen_ids: set[str] = set()
    gates = set(plan.frontmatter.get("engineering", {}).get("quality_gates", []))
    for index, test in enumerate(tests):
        if not isinstance(test, dict):
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Test contract {index} must be a mapping.", field=f"testing.tests[{index}]", path=plan.source_path))
            continue
        test_id = str(test.get("test_id", "")).strip()
        if not test_id:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Test contract {index} is missing test_id.", field=f"testing.tests[{index}].test_id", path=plan.source_path))
        elif test_id in seen_ids:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Duplicate test_id: {test_id}", field=f"testing.tests[{test_id}].test_id", path=plan.source_path))
        else:
            seen_ids.add(test_id)

        disposition = test.get("disposition")
        if disposition not in TEST_DISPOSITIONS:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Invalid test disposition for {test_id}: {disposition}", field=f"testing.tests[{test_id}].disposition", path=plan.source_path))
            continue
        files = test.get("files", [])
        if disposition in {"implement", "reuse"} and not files:
            issues.append(_issue("TEST_CONTRACT_MISMATCH", f"Test {test_id} must reference files.", field=f"testing.tests[{test_id}].files", path=plan.source_path))
        if disposition in {"reuse", "omit"} and not str(test.get("reason", "")).strip():
            issues.append(_issue("TEST_CONTRACT_MISMATCH", f"Test {test_id} requires a reason for disposition {disposition}.", field=f"testing.tests[{test_id}].reason", path=plan.source_path))
        if disposition == "implement" and str(test.get("gate_id", "")).strip() not in gates:
            issues.append(_issue("TEST_CONTRACT_MISMATCH", f"Test {test_id} references an unknown quality gate: {test.get('gate_id')}", field=f"testing.tests[{test_id}].gate_id", path=plan.source_path))

    for index, check in enumerate(testing.get("manual_checks", [])):
        if isinstance(check, dict) and not str(check.get("artifact", "")).strip():
            issues.append(_issue("TEST_CONTRACT_MISMATCH", f"Manual check {index} requires an artifact.", field=f"testing.manual_checks[{index}].artifact", path=plan.source_path))


def _validate_gate_definitions(gates: Any, issues: list[LintIssue], source_path: str) -> None:
    try:
        normalized_gates = _as_list(gates, "engineering.gates")
    except PlanError as exc:
        issues.append(_issue(exc.code, exc.message, field=exc.field, path=source_path))
        return
    seen: set[str] = set()
    for index, gate in enumerate(normalized_gates):
        if not isinstance(gate, dict):
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Gate {index} must be a mapping.", field=f"engineering.gates[{index}]", path=source_path))
            continue
        gate_id = str(gate.get("id", "")).strip()
        if not gate_id:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Gate {index} is missing an ID.", field=f"engineering.gates[{index}].id", path=source_path))
        elif gate_id in seen:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Duplicate gate ID: {gate_id}", field=f"engineering.gates.{gate_id}.id", path=source_path))
        else:
            seen.add(gate_id)
        if gate.get("kind") not in GATE_KINDS:
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Invalid gate kind for {gate_id}: {gate.get('kind')}", field=f"engineering.gates.{gate_id}.kind", path=source_path))
        if not isinstance(gate.get("blocking"), bool):
            issues.append(_issue("PLAN_SCHEMA_INVALID", f"Gate {gate_id} blocking must be boolean.", field=f"engineering.gates.{gate_id}.blocking", path=source_path))
        command = gate.get("command")
        if gate.get("kind") == "command" and (not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command)):
            issues.append(_issue("GATE_COMMAND_INVALID", f"Command gate {gate_id} must define a non-empty argv list.", field=f"engineering.gates.{gate_id}.command", path=source_path))


def _validate_workflow(plan: Plan, issues: list[LintIssue]) -> None:
    approval = plan.frontmatter.get("approval")
    if plan.status != "draft" and plan.frontmatter.get("content_hash") == "pending":
        issues.append(_issue(
            "PLAN_CONTENT_HASH_PENDING",
            "A plan with a pending content hash cannot be approved or executed.",
            field="content_hash",
            path=plan.source_path,
        ))
    if plan.status != "draft" and not approval:
        issues.append(_issue("PLAN_SCHEMA_INVALID", f"Status {plan.status} requires durable approval metadata.", field="approval", path=plan.source_path))

    batch_statuses = [str(row.get("status", "")).casefold() for row in plan.batches]
    if plan.status == "draft" and any(status in {"passed", "failed", "stale"} for status in batch_statuses):
        issues.append(_issue("INVALID_TRANSITION", "A draft plan cannot contain passed, failed, or stale batches.", path=plan.source_path))
    if plan.status == "approved" and any(status in {"in-progress", "validating", "stale"} for status in batch_statuses):
        issues.append(_issue("INVALID_TRANSITION", "An approved plan cannot contain active or stale batches.", path=plan.source_path))
    if plan.status == "executing" and not any(status in {"in-progress", "validating", "passed", "failed", "blocked", "stale"} for status in batch_statuses):
        issues.append(_issue("INVALID_TRANSITION", "An executing plan needs an active or completed batch.", path=plan.source_path))

    for row in plan.batches:
        batch_id = str(row.get("batch", "")).strip()
        batch_status = str(row.get("status", "")).casefold()
        linked_statuses = [
            str(task.get("status", ""))
            for task in plan.tasks
            if str(task.get("batch", "")) == batch_id
        ]
        if batch_status == "passed" and any(status not in {"done", "skipped"} for status in linked_statuses):
            issues.append(_issue(
                "PLAN_STATE_CONFLICT",
                f"Batch {batch_id} is passed, but it has unfinished tasks.",
                field=f"batches[{batch_id}].status",
                path=plan.source_path,
            ))
        if batch_status == "pending" and any(status == "done" for status in linked_statuses):
            issues.append(_issue(
                "PLAN_STATE_CONFLICT",
                f"Batch {batch_id} is pending, but it has completed tasks.",
                field=f"batches[{batch_id}].status",
                path=plan.source_path,
            ))


def _lint_parsed_plan(plan: Plan, root: Path) -> list[LintIssue]:
    issues: list[LintIssue] = list(plan.warnings)
    _validate_frontmatter(plan, issues)
    _validate_sections(plan, issues)
    _validate_references(plan, Path(root).resolve(), issues)
    _validate_tasks(plan, issues)
    _validate_batches(plan, issues)
    _validate_testing_contract(plan, issues)
    _validate_workflow(plan, issues)
    return issues


def lint_plan(path: str | Path, *, root: str | Path = ".") -> list[LintIssue]:
    """Parse and lint one plan; malformed files become issues instead of exceptions."""
    try:
        plan = parse_plan(path, root=root)
    except PlanError as exc:
        return [LintIssue(exc.code, exc.message, exc.field, exc.path)]
    return _lint_parsed_plan(plan, Path(root).resolve())


def is_plan_file(path: str | Path) -> bool:
    """Return false for legacy Markdown notes in a plans directory."""
    try:
        with Path(path).open("r", encoding="utf-8-sig", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    return line.strip() == "---"
    except OSError:
        return False
    return False


def lint_plans(plans_dir: str | Path, *, root: str | Path = ".") -> list[LintIssue]:
    """Lint every frontmatter-bearing Markdown file in a plans directory."""
    directory = Path(plans_dir)
    issues: list[LintIssue] = []
    plans: list[Plan] = []
    if not directory.is_dir():
        return [_issue("PLAN_NOT_FOUND", f"Plans directory not found: {directory}", path=directory.as_posix())]

    for path in sorted(directory.glob("*.md")):
        if not is_plan_file(path):
            continue
        try:
            plans.append(parse_plan(path, root=root))
        except PlanError as exc:
            issues.append(LintIssue(exc.code, exc.message, exc.field, exc.path))

    ids: dict[str, list[Plan]] = {}
    for plan in plans:
        try:
            ids.setdefault(str(plan.frontmatter["id"]), []).append(plan)
        except KeyError:
            continue

    for plan_id, duplicates in ids.items():
        if len(duplicates) > 1:
            for plan in duplicates:
                issues.append(_issue("PLAN_DUPLICATE_ID", f"Duplicate plan ID: {plan_id}", field="id", path=plan.source_path))

    root_path = Path(root).resolve()
    for plan in plans:
        issues.extend(_lint_parsed_plan(plan, root_path))
    return issues


def render_plan_template(*, slug: str, title: str | None = None, owner: str = "agent", last_writer: str = "codex") -> str:
    """Render a minimal valid product-plan skeleton."""
    clean_slug = _slugify(slug)
    today = datetime.now(timezone.utc).date()
    plan_title = title or clean_slug.replace("-", " ").title()
    frontmatter = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "id": f"{today.isoformat()}-{clean_slug}",
        "title": plan_title,
        "status": "draft",
        "created": f"{today.isoformat()}T00:00:00Z",
        "updated_at": f"{today.isoformat()}T00:00:00Z",
        "revision": 1,
        "content_hash": "pending",
        "revision_type": "semantic",
        "reapproval_required": False,
        "owner": owner,
        "last_writer": last_writer,
        "files": [],
        "symbols": [],
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
        "testing": {"approach": "test-with-change", "tests": [], "manual_checks": []},
        "approval": None,
    }
    safe_slug = _slugify(slug)
    frontmatter["testing"]["tests"] = [
        {
            "test_id": "T-001",
            "kind": "unit",
            "behavior": f"Verify the first task: {plan_title}.",
            "files": [f"tests/test_{safe_slug.replace('-', '_')}.py::test_first_task"],
            "gate_id": "unit-tests",
            "batch": "B1",
            "task": 1,
            "disposition": "implement",
        }
    ]
    body = f"""
# Goal

{plan_title}.

# Non-goals

TODO.

# Tasks

| # | Batch | Task | Depends on | Risk | Files | Symbols | Validation | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | B1 | TODO | none | medium | none | none | unit-tests gate | pending |

# Validation

Run the tests named in the testing contract.

# Testing strategy

TODO: add structured test contracts in frontmatter.

# Execution notes

Implement one validated batch at a time.

# Engineering requirements

TODO.

# Quality gates

unit-tests is blocking.

# Batches

| Batch | Purpose | Depends on | Status | Last validation |
|---|---|---|---|---|
| B1 | First validated batch | none | pending | none |
"""
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=True, allow_unicode=True)}---\n{body.lstrip()}\n"


def plan_summary(plan: Plan) -> dict[str, Any]:
    """Return a bounded summary suitable for CLI or agent output."""
    next_batch = next((row.get("batch") for row in plan.batches if row.get("status") == "pending"), None)
    return {
        "id": plan.id,
        "title": plan.frontmatter.get("title"),
        "status": plan.status,
        "revision": plan.frontmatter.get("revision"),
        "engineering_profile": plan.engineering_profile,
        "reapproval_required": plan.frontmatter.get("reapproval_required"),
        "next_batch": next_batch,
        "path": plan.source_path,
        "warnings": [
            {"code": issue.code, "message": issue.message}
            for issue in plan.warnings
        ],
    }


def find_plan(plan_id: str, plans_dir: str | Path, *, root: str | Path = ".") -> Plan:
    """Find one parsed plan by exact durable ID."""
    directory = Path(plans_dir)
    if not directory.is_dir():
        raise PlanError("PLAN_NOT_FOUND", f"Plans directory not found: {directory}", path=directory.as_posix())
    matches: list[Plan] = []
    for path in sorted(directory.glob("*.md")):
        if not is_plan_file(path):
            continue
        plan = parse_plan(path, root=root)
        if plan.id == plan_id:
            matches.append(plan)
    if not matches:
        raise PlanError("PLAN_NOT_FOUND", f"Plan not found: {plan_id}", path=directory.as_posix())
    if len(matches) > 1:
        raise PlanError("PLAN_DUPLICATE_ID", f"Duplicate plan ID: {plan_id}", field="id")
    return matches[0]


def plan_status(plans_dir: str | Path, *, root: str | Path = ".") -> dict[str, Any]:
    """Return a bounded, grouped status view without rendering plan bodies."""
    directory = Path(plans_dir)
    if not directory.is_dir():
        raise PlanError("PLAN_NOT_FOUND", f"Plans directory not found: {directory}", path=directory.as_posix())
    grouped: dict[str, list[dict[str, Any]]] = {}
    issues: list[LintIssue] = []
    total = 0
    for path in sorted(directory.glob("*.md")):
        if not is_plan_file(path):
            continue
        try:
            plan = parse_plan(path, root=root)
        except PlanError as exc:
            issues.append(LintIssue(exc.code, exc.message, exc.field, exc.path))
            continue
        total += 1
        grouped.setdefault(plan.status, []).append(plan_summary(plan))
    return {
        "total": total,
        "groups": [
            {"status": status, "plans": grouped[status]}
            for status in sorted(grouped)
        ],
        "warnings": [
            {"code": issue.code, "message": issue.message, "path": issue.path}
            for issue in issues
        ],
    }


def plan_view(plan: Plan, *, view: str = "summary") -> dict[str, Any]:
    """Return a bounded CLI/agent view without exposing plan bodies."""
    if view not in {"summary", "full", "execution", "engineering", "evidence", "graph"}:
        raise PlanError("PLAN_SCHEMA_INVALID", f"Unknown plan view: {view}", field="view")
    if view == "summary":
        return plan_summary(plan)
    if view == "execution":
        return {
            "id": plan.id,
            "status": plan.status,
            "revision": plan.frontmatter.get("revision"),
            "next_batch": next((row.get("batch") for row in plan.batches if row.get("status") == "pending"), None),
            "tasks": plan.tasks,
            "validation": plan.sections.get("validation", ""),
            "testing": plan.frontmatter.get("testing", {}),
        }
    if view == "engineering":
        engineering = dict(plan.frontmatter.get("engineering", {}))
        engineering["engineering_requirements"] = plan.sections.get("engineering requirements", "")
        return {
            "id": plan.id,
            "profile": engineering.get("profile"),
            "engineering": engineering,
            "architecture_style": engineering.get("architecture_style"),
            "standards": engineering.get("standards", []),
            "quality_gates": engineering.get("quality_gates", []),
            "engineering_requirements": engineering["engineering_requirements"],
        }
    if view == "evidence":
        return {
            "id": plan.id,
            "evidence": plan.frontmatter.get("evidence", []),
            "context_pages": plan.frontmatter.get("context_pages", []),
        }
    if view == "graph":
        return plan_graph(plan)
    summary = plan_summary(plan)
    return {
        **summary,
        "section_names": sorted(plan.sections),
        "tasks": plan.tasks,
        "batches": plan.batches,
    }


PLAN_GRAPH_MAX_NODES = 80
PLAN_GRAPH_MAX_EDGES = 160


def _mermaid_label(value: Any) -> str:
    return str(value).replace('"', "'").replace("\n", " ")


def plan_graph(plan: Plan, *, max_nodes: int = PLAN_GRAPH_MAX_NODES, max_edges: int = PLAN_GRAPH_MAX_EDGES) -> dict[str, Any]:
    """Render a bounded Mermaid graph from structured plan tables."""
    if max_nodes < 1 or max_edges < 1:
        raise PlanError("PLAN_SCHEMA_INVALID", "Graph limits must be positive.", field="graph")

    nodes: list[str] = []
    edges: list[str] = []
    dependencies: list[tuple[str, str]] = []
    truncated = False

    def add_node(node_id: str, label: str) -> None:
        nonlocal truncated
        if len(nodes) >= max_nodes:
            truncated = True
            return
        nodes.append(f'  {node_id}["{label}"]')

    def add_edge(source: str, target: str) -> None:
        nonlocal truncated
        if len(nodes) > max_nodes or len(edges) >= max_edges:
            truncated = True
            return
        edge = f"  {source} --> {target}"
        if edge not in edges:
            edges.append(edge)

    for batch in plan.batches:
        batch_id = str(batch.get("batch", "")).strip()
        if not batch_id:
            continue
        add_node(batch_id, f"Batch {batch_id} · {batch.get('status', 'unknown')}")
        dependency = str(batch.get("depends on", "")).strip()
        if dependency and dependency.casefold() != "none":
            for item in re.split(r"[,;]\s*", dependency):
                if item:
                    dependencies.append((item, batch_id))

    for task in plan.tasks:
        number = task.get("number", 0)
        task_id = f"T{number}"
        add_node(task_id, f"Task {number} · {task.get('status', 'unknown')}")
        batch_id = str(task.get("batch", "")).strip()
        if batch_id:
            add_edge(batch_id, task_id)
        dependency = str(task.get("depends on", "")).strip()
        if dependency and dependency.casefold() != "none":
            for item in re.split(r"[,;]\s*", dependency):
                if item.isdigit():
                    dependencies.append((f"T{item}", task_id))

    cycle_detected = False
    adjacency: dict[str, set[str]] = {}
    for source, target in dependencies:
        adjacency.setdefault(source, set()).add(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        nonlocal cycle_detected
        if node_id in visiting:
            cycle_detected = True
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for target in adjacency.get(node_id, set()):
            visit(target)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(adjacency):
        visit(node_id)

    for source, target in dependencies:
        add_edge(source, target)

    mermaid_lines = ["flowchart TD", *nodes, *edges]
    return {
        "id": plan.id,
        "format": "mermaid",
        "mermaid": "\n".join(mermaid_lines),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "cycle_detected": cycle_detected,
        "truncated": truncated,
    }
