"""Pure workflow operations for durable Markdown plan revisions.

This module is intentionally independent from Typer, Rich, SQLite, and MCP.
The Markdown file remains authoritative; snapshots and events are audit aids.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .plans import Plan, PlanError, find_plan, lint_plan, parse_plan, parse_plan_text, render_plan_template
from .plan_memory import fingerprint_batch_inputs


_APPROVAL_BASES = {"conversation", "review-doc", "issue", "ci-review"}
_SEMANTIC_FRONTMATTER_KEYS = {
    "files",
    "symbols",
    "context_pages",
    "evidence",
    "change_control",
    "engineering",
    "testing",
}
_SEMANTIC_SECTIONS = {
    "goal",
    "non-goals",
    "architecture decisions",
    "security and privacy",
    "compatibility and migration",
    "quality gates",
}
_WORKFLOW_STATE_FRONTMATTER_KEYS = {
    "revision",
    "revision_type",
    "reapproval_required",
    "content_hash",
    "status",
    "updated_at",
    "last_writer",
    "approval",
}


@dataclass(frozen=True)
class WorkflowResult:
    """The result of one successful workflow mutation."""

    plan: Plan
    snapshot_path: Path
    event_path: Path


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_plan_hash(plan: Plan) -> str:
    """Hash the canonical plan content, excluding the stored hash itself."""
    frontmatter = {key: value for key, value in plan.frontmatter.items() if key != "content_hash"}
    return _sha256_json({"body": plan.body, "frontmatter": frontmatter})


def _ensure_inside_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise PlanError("PLAN_OUTSIDE_ROOT", f"Path is outside project root: {path}", path=path.as_posix())
    return resolved


def _copy_plan(plan: Plan, *, frontmatter: dict[str, Any]) -> Plan:
    return Plan(
        path=plan.path,
        source_path=plan.source_path,
        frontmatter=frontmatter,
        body=plan.body,
        sections=plan.sections,
        tasks=plan.tasks,
        batches=plan.batches,
        warnings=plan.warnings,
    )


def _write_plan(plan: Plan) -> None:
    serialized = f"---\n{yaml.safe_dump(plan.frontmatter, sort_keys=True, allow_unicode=True)}---\n{plan.body}\n"
    plan.path.parent.mkdir(parents=True, exist_ok=True)
    plan.path.write_text(serialized, encoding="utf-8", newline="\n")


def _plans_dir(root: Path, plans_dir: Path) -> Path:
    directory = plans_dir if plans_dir.is_absolute() else root / plans_dir
    return _ensure_inside_root(directory, root)


def _workflow_dir(root: Path, plans_dir: Path, plan_id: str) -> Path:
    return _ensure_inside_root(_plans_dir(root, plans_dir) / "revisions" / plan_id, root)


def _snapshot_path(directory: Path, revision: int) -> Path:
    return directory / f"{revision:04d}.md"


def _append_event(event_path: Path, payload: dict[str, Any]) -> None:
    event_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with event_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def _snapshot(plan: Plan, directory: Path, event_path: Path, *, event: str, actor: str, reason: str | None = None) -> WorkflowResult:
    destination = _snapshot_path(directory, int(plan.frontmatter["revision"]))
    if destination.exists():
        raise PlanError("PLAN_REVISION_SNAPSHOT_EXISTS", f"Revision snapshot already exists: {destination}", path=destination.as_posix())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(plan.path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    payload = {
        "at": _iso_now(),
        "actor": actor,
        "content_hash": plan.frontmatter["content_hash"],
        "event": event,
        "plan_id": plan.id,
        "reason": reason,
        "revision": int(plan.frontmatter["revision"]),
    }
    _append_event(event_path, payload)
    return WorkflowResult(plan=plan, snapshot_path=destination, event_path=event_path)


def _require_lint_clean(plan: Plan, root: Path) -> None:
    issues = lint_plan(plan.path, root=root)
    if issues:
        summary = "; ".join(f"{issue.code}: {issue.message}" for issue in issues)
        raise PlanError("PLAN_LINT_FAILED", summary, path=plan.source_path)


def _require_current(plan: Plan, *, allow_stale: bool = False) -> None:
    stored = plan.frontmatter.get("content_hash")
    canonical = canonical_plan_hash(plan)
    if stored != canonical and not allow_stale:
        raise PlanError(
            "PLAN_CONTENT_HASH_STALE",
            "Plan content hash does not match the canonical content.",
            field="content_hash",
            path=plan.source_path,
        )


def _require_expected_revision(plan: Plan, expected_revision: int | None) -> None:
    if expected_revision is not None and int(plan.frontmatter["revision"]) != expected_revision:
        raise PlanError(
            "PLAN_REVISION_CONFLICT",
            f"Expected plan revision {expected_revision}, found {plan.frontmatter['revision']}.",
            field="revision",
            path=plan.source_path,
        )


def _engineering_hashes(plan: Plan) -> tuple[str, str]:
    engineering = plan.frontmatter.get("engineering", {})
    profile_payload = {
        "architecture_style": engineering.get("architecture_style"),
        "plain_language": engineering.get("plain_language"),
        "profile": engineering.get("profile"),
        "profile_revision": engineering.get("profile_revision"),
        "standards": engineering.get("standards", []),
    }
    gate_payload = engineering.get("quality_gates", [])
    return _sha256_json(profile_payload), _sha256_json(gate_payload)


def create_plan(
    root: str | Path,
    plans_dir: str | Path,
    *,
    slug: str,
    title: str | None = None,
    last_writer: str = "codex",
) -> WorkflowResult:
    """Create a new hashed plan and its first durable revision snapshot."""
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, Path(plans_dir))
    text = render_plan_template(slug=slug, title=title)
    parsed = parse_plan_text(text)
    parsed.frontmatter["content_hash"] = canonical_plan_hash(parsed)
    target = directory / f"{parsed.id}.md"
    if target.exists():
        raise PlanError("PLAN_ALREADY_EXISTS", f"Plan already exists: {target}", path=target.as_posix())
    directory.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"---\n{yaml.safe_dump(parsed.frontmatter, sort_keys=True, allow_unicode=True)}---\n{parsed.body}\n",
        encoding="utf-8",
        newline="\n",
    )
    plan = parse_plan(target, root=root_path)
    workflow_dir = _workflow_dir(root_path, directory, plan.id)
    write_plan_projection(root_path, plan)
    event_path = workflow_dir / "events.jsonl"
    result = _snapshot(plan, workflow_dir, event_path, event="created", actor=last_writer)
    return WorkflowResult(plan=plan, snapshot_path=result.snapshot_path, event_path=result.event_path)


def approve_plan(
    root: str | Path,
    plans_dir: str | Path,
    plan_id: str,
    *,
    approved_by: str,
    basis: str = "conversation",
    notes: str | None = None,
    expected_revision: int | None = None,
) -> WorkflowResult:
    """Lint a draft and durably record a human approval decision."""
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, Path(plans_dir))
    plan = find_plan(plan_id, directory, root=root_path)
    _require_lint_clean(plan, root_path)
    _require_expected_revision(plan, expected_revision)
    if plan.frontmatter.get("content_hash") == "pending":
        raise PlanError(
            "PLAN_CONTENT_HASH_PENDING",
            "A plan with a pending content hash must be revised to a canonical hash before approval.",
            field="content_hash",
            path=plan.source_path,
        )
    _require_current(plan)
    if plan.status != "draft":
        raise PlanError("PLAN_STATUS_INVALID", f"Only draft plans can be approved; found {plan.status}.", field="status", path=plan.source_path)
    if not approved_by.strip():
        raise PlanError("PLAN_APPROVAL_INVALID", "Approval requires an approver.", field="approval.approved_by", path=plan.source_path)
    if basis not in _APPROVAL_BASES:
        raise PlanError("PLAN_APPROVAL_INVALID", f"Invalid approval basis: {basis}", field="approval.basis", path=plan.source_path)

    profile_hash, gate_set_hash = _engineering_hashes(plan)
    frontmatter = dict(plan.frontmatter)
    frontmatter.update(
        {
            "approval": {
                "approved_at": _iso_now(),
                "approved_by": approved_by.strip(),
                "basis": basis,
                "decision": "approved",
                "gate_set_hash": gate_set_hash,
                "notes": notes,
                "profile_hash": profile_hash,
            },
            "reapproval_required": False,
            "revision_type": "state",
            "status": "approved",
        }
    )
    next_plan = _copy_plan(plan, frontmatter=frontmatter)
    next_plan.frontmatter["revision"] = int(plan.frontmatter["revision"]) + 1
    next_plan.frontmatter["updated_at"] = _iso_now()
    next_plan.frontmatter["last_writer"] = approved_by
    next_plan.frontmatter["content_hash"] = canonical_plan_hash(next_plan)
    _write_plan(next_plan)
    next_plan = parse_plan(next_plan.path, root=root_path)
    workflow_dir = _workflow_dir(root_path, directory, plan_id)
    result = _snapshot(
        next_plan,
        workflow_dir,
        workflow_dir / "events.jsonl",
        event="approved",
        actor=approved_by,
        reason=notes,
    )
    write_plan_projection(root_path, result.plan)
    return result


def reapprove_plan(
    root: str | Path,
    plans_dir: str | Path,
    plan_id: str,
    *,
    approved_by: str,
    basis: str = "conversation",
    notes: str | None = None,
    expected_revision: int | None = None,
) -> WorkflowResult:
    """Durably record human reapproval after a semantic revision."""
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, Path(plans_dir))
    plan = find_plan(plan_id, directory, root=root_path)
    _require_lint_clean(plan, root_path)
    _require_expected_revision(plan, expected_revision)
    if plan.frontmatter.get("content_hash") == "pending":
        raise PlanError(
            "PLAN_CONTENT_HASH_PENDING",
            "A plan with a pending content hash must be revised to a canonical hash before reapproval.",
            field="content_hash",
            path=plan.source_path,
        )
    _require_current(plan)
    if plan.status not in {"approved", "executing"}:
        raise PlanError(
            "PLAN_STATUS_INVALID",
            f"Only approved or executing plans can be reapproved; found {plan.status}.",
            field="status",
            path=plan.source_path,
        )
    if plan.frontmatter.get("reapproval_required") is not True:
        raise PlanError(
            "PLAN_REAPPROVAL_NOT_REQUIRED",
            "Plan does not require reapproval.",
            field="reapproval_required",
            path=plan.source_path,
        )
    if not approved_by.strip():
        raise PlanError("PLAN_APPROVAL_INVALID", "Reapproval requires an approver.", field="approval.approved_by", path=plan.source_path)
    if basis not in _APPROVAL_BASES:
        raise PlanError("PLAN_APPROVAL_INVALID", f"Invalid reapproval basis: {basis}", field="approval.basis", path=plan.source_path)

    profile_hash, gate_set_hash = _engineering_hashes(plan)
    frontmatter = dict(plan.frontmatter)
    frontmatter.update(
        {
            "approval": {
                "approved_at": _iso_now(),
                "approved_by": approved_by.strip(),
                "basis": basis,
                "decision": "reapproved",
                "gate_set_hash": gate_set_hash,
                "notes": notes,
                "profile_hash": profile_hash,
            },
            "reapproval_required": False,
            "revision_type": "state",
        }
    )
    next_plan = _copy_plan(plan, frontmatter=frontmatter)
    next_plan.frontmatter["revision"] = int(plan.frontmatter["revision"]) + 1
    next_plan.frontmatter["updated_at"] = _iso_now()
    next_plan.frontmatter["last_writer"] = approved_by
    next_plan.frontmatter["content_hash"] = canonical_plan_hash(next_plan)
    _write_plan(next_plan)
    next_plan = parse_plan(next_plan.path, root=root_path)
    workflow_dir = _workflow_dir(root_path, directory, plan_id)
    result = _snapshot(
        next_plan,
        workflow_dir,
        workflow_dir / "events.jsonl",
        event="reapproved",
        actor=approved_by,
        reason=notes,
    )
    write_plan_projection(root_path, result.plan)
    return result


def _classification_for(old: Plan, new: Plan) -> str:
    for key in _SEMANTIC_FRONTMATTER_KEYS:
        if old.frontmatter.get(key) != new.frontmatter.get(key):
            return "semantic"

    for name in _SEMANTIC_SECTIONS:
        if old.sections.get(name, "").strip() != new.sections.get(name, "").strip():
            return "semantic"

    old_tasks = [{key: value for key, value in row.items() if key != "status"} for row in old.tasks]
    new_tasks = [{key: value for key, value in row.items() if key != "status"} for row in new.tasks]
    if old_tasks != new_tasks:
        return "semantic"

    old_batches = [{key: value for key, value in row.items() if key != "status"} for row in old.batches]
    new_batches = [{key: value for key, value in row.items() if key != "status"} for row in new.batches]
    if old_batches != new_batches:
        return "semantic"

    state_changed = (
        old.status != new.status
        or old.frontmatter.get("reapproval_required") != new.frontmatter.get("reapproval_required")
        or [row.get("status") for row in old.tasks] != [row.get("status") for row in new.tasks]
        or [row.get("status") for row in old.batches] != [row.get("status") for row in new.batches]
    )
    if state_changed:
        return "state"

    old_semantic_frontmatter = {key: value for key, value in old.frontmatter.items() if key not in _WORKFLOW_STATE_FRONTMATTER_KEYS}
    new_semantic_frontmatter = {key: value for key, value in new.frontmatter.items() if key not in _WORKFLOW_STATE_FRONTMATTER_KEYS}
    normalized_old_body = " ".join(old.body.split())
    normalized_new_body = " ".join(new.body.split())
    if old_semantic_frontmatter == new_semantic_frontmatter and normalized_old_body == normalized_new_body:
        return "formatting"
    return "state"


def _load_snapshot(root: Path, workflow_dir: Path, revision: int) -> Plan:
    snapshot = _snapshot_path(workflow_dir, revision)
    if not snapshot.is_file():
        raise PlanError("PLAN_REVISION_NOT_FOUND", f"Revision snapshot not found: {revision}", path=snapshot.as_posix())
    return parse_plan(snapshot, root=root)


def diff_plan(
    root: str | Path,
    plans_dir: str | Path,
    plan_id: str,
    *,
    from_revision: int,
    to_revision: int,
) -> dict[str, Any]:
    """Compare two durable revision snapshots and classify the dominant change."""
    root_path = Path(root).resolve()
    workflow_dir = _workflow_dir(root_path, Path(plans_dir), plan_id)
    old = _load_snapshot(root_path, workflow_dir, from_revision)
    new = _load_snapshot(root_path, workflow_dir, to_revision)
    revision_type = _classification_for(old, new)
    return {
        "plan_id": plan_id,
        "from_revision": from_revision,
        "to_revision": to_revision,
        "semantic": revision_type == "semantic",
        "state": revision_type == "state",
        "formatting": revision_type == "formatting",
        "revision_type": revision_type,
    }


def plan_projection_path(root: str | Path, plan_id: str) -> Path:
    """Return the rebuildable projection path for one plan."""
    root_path = Path(root).resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", plan_id):
        raise PlanError("PLAN_SCHEMA_INVALID", "Plan ID contains invalid path characters.", field="id")
    return root_path / ".codeatlas" / "plans" / f"{plan_id}.json"


def write_plan_projection(root: str | Path, plan: Plan) -> Path:
    """Write a bounded, rebuildable projection without plan bodies."""
    path = plan_projection_path(root, plan.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "id": plan.id,
        "title": plan.frontmatter.get("title"),
        "status": plan.status,
        "revision": int(plan.frontmatter["revision"]),
        "content_hash": plan.frontmatter.get("content_hash"),
        "source_path": plan.source_path,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _latest_snapshot(workflow_dir: Path) -> Path:
    snapshots = sorted(workflow_dir.glob("[0-9][0-9][0-9][0-9].md"))
    if not snapshots:
        raise PlanError("PLAN_REVISION_NOT_FOUND", "No durable revision snapshot is available.", path=workflow_dir.as_posix())
    return snapshots[-1]


def revise_plan(
    root: str | Path,
    plans_dir: str | Path,
    plan_id: str,
    *,
    expected_revision: int | None = None,
    allow_stale: bool = False,
    bootstrap: bool = False,
    reason: str | None = None,
    writer: str = "codex",
) -> WorkflowResult:
    """Record the current Markdown file as the next accepted revision."""
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, Path(plans_dir))
    plan = find_plan(plan_id, directory, root=root_path)
    _require_lint_clean(plan, root_path)
    _require_expected_revision(plan, expected_revision)
    _require_current(plan, allow_stale=allow_stale)
    if plan.status not in {"draft", "approved", "executing", "blocked"}:
        raise PlanError("PLAN_STATUS_INVALID", f"Plan status cannot be revised: {plan.status}", field="status", path=plan.source_path)

    workflow_dir = _workflow_dir(root_path, directory, plan_id)
    if not any(workflow_dir.glob("[0-9][0-9][0-9][0-9].md")):
        if not bootstrap:
            raise PlanError(
                "PLAN_REVISION_NOT_FOUND",
                "No durable revision snapshot is available.",
                path=workflow_dir.as_posix(),
            )
        _snapshot(
            plan,
            workflow_dir,
            workflow_dir / "events.jsonl",
            event="legacy-baseline",
            actor=writer,
            reason=reason or "Bootstrap migration baseline for a pre-workflow plan.",
        )
    previous_path = _latest_snapshot(workflow_dir)
    previous = parse_plan(previous_path, root=root_path)
    revision_type = _classification_for(previous, plan)
    if revision_type == "formatting":
        revision_type = "state"
    reapproval_required = revision_type == "semantic" and plan.status in {"approved", "executing"}
    frontmatter = dict(plan.frontmatter)
    frontmatter.update(
        {
            "reapproval_required": reapproval_required,
            "revision_type": revision_type,
        }
    )
    next_plan = _copy_plan(plan, frontmatter=frontmatter)
    next_plan.frontmatter["revision"] = int(plan.frontmatter["revision"]) + 1
    next_plan.frontmatter["updated_at"] = _iso_now()
    next_plan.frontmatter["last_writer"] = writer
    next_plan.frontmatter["content_hash"] = canonical_plan_hash(next_plan)
    _write_plan(next_plan)
    next_plan = parse_plan(next_plan.path, root=root_path)
    write_plan_projection(root_path, next_plan)
    return _snapshot(
        next_plan,
        workflow_dir,
        workflow_dir / "events.jsonl",
        event="revised",
        actor=writer,
        reason=reason,
    )


def _append_execution_log(body: str, entry: str) -> str:
    if re.search(r"^#\s+Execution log\s*$", body, flags=re.MULTILINE | re.IGNORECASE):
        return body.rstrip() + f"\n- {entry}\n"
    return body.rstrip() + f"\n\n# Execution log\n\n- {entry}\n"


def _sync_body_tables(plan: Plan) -> None:
    """Persist parsed task/batch state back into the authoritative Markdown tables."""
    lines = plan.body.splitlines()
    current: str | None = None
    headers: list[str] | None = None
    for index, line in enumerate(lines):
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            current = heading.group(1).strip().casefold()
            headers = None
            continue
        if current not in {"tasks", "batches"} or not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
            continue
        if headers is None:
            headers = [cell.casefold() for cell in cells]
            continue
        row = dict(zip(headers, cells, strict=True))
        if current == "tasks":
            task = next((item for item in plan.tasks if str(item.get("#", "")) == row.get("#")), None)
            if task is not None:
                cells[headers.index("status")] = str(task.get("status", cells[-1]))
        else:
            item = next(
                (entry for entry in plan.batches if str(entry.get("batch", "")) == row.get("batch")),
                None,
            )
            if item is not None:
                cells[headers.index("status")] = str(item.get("status", ""))
                if "last validation" in headers:
                    cells[headers.index("last validation")] = str(item.get("last_validation", ""))
        lines[index] = "| " + " | ".join(cells) + " |"
    plan.body = "\n".join(lines) + ("\n" if plan.body.endswith("\n") else "")


def _commit_state_revision(
    root: Path,
    directory: Path,
    plan: Plan,
    *,
    event: str,
    actor: str,
    reason: str | None = None,
) -> WorkflowResult:
    workflow_dir = _workflow_dir(root, directory, plan.id)
    next_plan = _copy_plan(plan, frontmatter=dict(plan.frontmatter))
    next_plan.frontmatter["revision"] = int(plan.frontmatter["revision"]) + 1
    next_plan.frontmatter["updated_at"] = _iso_now()
    next_plan.frontmatter["last_writer"] = actor
    next_plan.frontmatter["revision_type"] = "state"
    next_plan.frontmatter["content_hash"] = canonical_plan_hash(next_plan)
    _write_plan(next_plan)
    next_plan = parse_plan(next_plan.path, root=root)
    result = _snapshot(
        next_plan,
        workflow_dir,
        workflow_dir / "events.jsonl",
        event=event,
        actor=actor,
        reason=reason,
    )
    write_plan_projection(root, next_plan)
    return result


def _require_execution_ready(plan: Plan, *, expected_revision: int | None, actor: str) -> None:
    if not actor.strip():
        raise PlanError("PLAN_ACTOR_INVALID", "Execution requires an actor.", field="actor", path=plan.source_path)
    _require_expected_revision(plan, expected_revision)
    _require_current(plan)
    if plan.status not in {"approved", "executing"}:
        raise PlanError("PLAN_STATUS_INVALID", f"Only approved plans can execute; found {plan.status}.", field="status", path=plan.source_path)
    if plan.frontmatter.get("reapproval_required") is True:
        raise PlanError("PLAN_REAPPROVAL_REQUIRED", "A semantic revision requires human reapproval before execution.", field="reapproval_required", path=plan.source_path)


def _batch_row(plan: Plan, batch: str) -> dict[str, Any]:
    row = next((item for item in plan.batches if str(item.get("batch", "")) == batch), None)
    if row is None:
        raise PlanError("PLAN_BATCH_NOT_FOUND", f"Batch not found: {batch}", field="batches.batch", path=plan.source_path)
    return row


def start_batch(
    root: str | Path,
    plans_dir: str | Path,
    plan_id: str,
    *,
    batch: str,
    expected_revision: int | None = None,
    actor: str = "codex",
) -> WorkflowResult:
    """Start one pending or blocked batch and its linked tasks."""
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, Path(plans_dir))
    plan = find_plan(plan_id, directory, root=root_path)
    _require_execution_ready(plan, expected_revision=expected_revision, actor=actor)
    row = _batch_row(plan, batch)
    if str(row.get("status", "")) not in {"pending", "blocked"}:
        raise PlanError(
            "INVALID_TRANSITION",
            f"Batch {batch} cannot start from status {row.get('status')}.",
            field=f"batches[{batch}].status",
            path=plan.source_path,
        )

    row["status"] = "in-progress"
    for task in plan.tasks:
        if str(task.get("batch", "")) == batch and task.get("status") == "pending":
            task["status"] = "in-progress"
    plan.frontmatter["status"] = "executing"
    plan.frontmatter["batch_started_revision"] = int(plan.frontmatter["revision"])
    plan.body = _append_execution_log(plan.body, f"Started batch {batch}.")
    _sync_body_tables(plan)
    return _commit_state_revision(
        root_path,
        directory,
        plan,
        event="batch_started",
        actor=actor,
        reason=batch,
    )


def _required_gate_ids(plan: Plan, batch: str) -> set[str]:
    testing = plan.frontmatter.get("testing", {})
    referenced = {
        str(test.get("gate_id", ""))
        for test in testing.get("tests", [])
        if isinstance(test, dict)
        and str(test.get("batch", "")) == batch
        and test.get("disposition") != "omit"
        and str(test.get("gate_id", "")).strip()
    }
    if referenced:
        return referenced
    engineering = plan.frontmatter.get("engineering", {})
    definitions = engineering.get("gates", [])
    if definitions:
        return {
            str(gate.get("id", ""))
            for gate in definitions
            if isinstance(gate, dict) and gate.get("blocking") is True and str(gate.get("id", "")).strip()
        }
    return {str(gate) for gate in engineering.get("quality_gates", []) if str(gate).strip()}


def _require_passing_gate_results(plan: Plan, batch: str, root_path: Path) -> None:
    gate_ids = _required_gate_ids(plan, batch)
    revision = int(plan.frontmatter["revision"])
    started_revision = int(plan.frontmatter.get("batch_started_revision", revision))
    results = [item for item in plan.frontmatter.get("gate_results", []) if isinstance(item, dict)]
    for gate_id in sorted(gate_ids):
        matching = [
            item for item in results
            if str(item.get("gate_id", "")) == gate_id
            and str(item.get("batch", "")) == batch
            and started_revision <= int(item.get("plan_revision", 0)) <= revision
        ]
        if not matching:
            raise PlanError(
                "GATE_EVIDENCE_REQUIRED",
                f"Batch {batch} has no passing evidence for gate {gate_id} since revision {started_revision}.",
                field=f"gate_results.{gate_id}",
                path=plan.source_path,
            )
        latest = max(matching, key=lambda item: int(item.get("plan_revision", 0)))
        if str(latest.get("outcome", "")) != "passed":
            raise PlanError(
                "GATE_RESULT_FAILED",
                f"Batch {batch} has a failed gate result: {gate_id}.",
                field=f"gate_results.{gate_id}",
                path=plan.source_path,
            )
        recorded_fingerprint = str(latest.get("input_fingerprint", "")).strip()
        if not recorded_fingerprint:
            raise PlanError(
                "GATE_FINGERPRINT_REQUIRED",
                f"Gate result {gate_id} for batch {batch} is missing an input fingerprint.",
                field=f"gate_results.{gate_id}.input_fingerprint",
                path=plan.source_path,
            )
        try:
            current_fingerprint = fingerprint_batch_inputs(root_path, plan, batch)["fingerprint"]
        except PlanError as exc:
            raise PlanError(
                exc.code,
                f"Could not verify gate fingerprint for batch {batch}: {exc.message}",
                field=f"gate_results.{gate_id}.input_fingerprint",
                path=plan.source_path,
            ) from exc
        if recorded_fingerprint != current_fingerprint:
            raise PlanError(
                "GATE_EVIDENCE_STALE",
                f"Gate result {gate_id} for batch {batch} has stale input evidence; re-run the gate.",
                field=f"gate_results.{gate_id}.input_fingerprint",
                path=plan.source_path,
            )


def complete_batch(
    root: str | Path,
    plans_dir: str | Path,
    plan_id: str,
    *,
    batch: str,
    expected_revision: int | None = None,
    actor: str = "codex",
) -> WorkflowResult:
    """Mark a batch passed only when every required gate has passing evidence."""
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, Path(plans_dir))
    plan = find_plan(plan_id, directory, root=root_path)
    _require_execution_ready(plan, expected_revision=expected_revision, actor=actor)
    row = _batch_row(plan, batch)
    if str(row.get("status", "")) not in {"in-progress", "validating", "failed"}:
        raise PlanError(
            "INVALID_TRANSITION",
            f"Batch {batch} cannot complete from status {row.get('status')}.",
            field=f"batches[{batch}].status",
            path=plan.source_path,
        )

    _require_passing_gate_results(plan, batch, root_path)
    _require_test_contract(plan, batch, root_path)
    row["status"] = "passed"
    row["last_validation"] = _iso_now()
    for task in plan.tasks:
        if str(task.get("batch", "")) == batch and task.get("status") in {"in-progress", "validating", "blocked"}:
            task["status"] = "done"
    if plan.batches and all(str(item.get("status", "")) == "passed" for item in plan.batches):
        plan.frontmatter["status"] = "done"
    plan.body = _append_execution_log(plan.body, f"Completed batch {batch} with passing gate evidence.")
    _sync_body_tables(plan)
    return _commit_state_revision(
        root_path,
        directory,
        plan,
        event="batch_completed",
        actor=actor,
        reason=batch,
    )


def mark_batch_stale(
    root: str | Path,
    plans_dir: str | Path,
    plan_id: str,
    *,
    batch: str,
    reason: str,
    expected_revision: int | None = None,
    actor: str = "codex",
) -> WorkflowResult:
    """Mark a passed batch stale without silently reopening the plan status."""
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, Path(plans_dir))
    plan = find_plan(plan_id, directory, root=root_path)
    if not actor.strip():
        raise PlanError("PLAN_ACTOR_INVALID", "Stale marking requires an actor.", field="actor", path=plan.source_path)
    _require_expected_revision(plan, expected_revision)
    _require_current(plan)
    if not reason.strip():
        raise PlanError("PLAN_STALE_REASON_REQUIRED", "Stale evidence requires a reason.", field="reason", path=plan.source_path)
    row = _batch_row(plan, batch)
    if str(row.get("status", "")) != "passed":
        raise PlanError(
            "INVALID_TRANSITION",
            f"Only a passed batch can become stale; batch {batch} is {row.get('status')}.",
            field=f"batches[{batch}].status",
            path=plan.source_path,
        )

    row["status"] = "stale"
    stale_entry = {
        "at": _iso_now(),
        "actor": actor,
        "batch": batch,
        "reason": reason,
        "plan_revision": int(plan.frontmatter["revision"]),
    }
    plan.frontmatter["stale_evidence"] = [*plan.frontmatter.get("stale_evidence", []), stale_entry]
    plan.body = _append_execution_log(plan.body, f"Marked batch {batch} stale: {reason}")
    _sync_body_tables(plan)
    return _commit_state_revision(
        root_path,
        directory,
        plan,
        event="batch_stale",
        actor=actor,
        reason=reason,
    )


def _gate_definition(plan: Plan, gate_id: str) -> dict[str, Any]:
    engineering = plan.frontmatter.get("engineering", {})
    definitions = engineering.get("gates", [])
    for definition in definitions:
        if isinstance(definition, dict) and str(definition.get("id", "")) == gate_id:
            return definition
    if gate_id in {str(gate) for gate in engineering.get("quality_gates", [])}:
        return {"id": gate_id, "kind": "command", "blocking": True}
    raise PlanError(
        "GATE_DEFINITION_NOT_FOUND",
        f"Gate definition not found: {gate_id}",
        field=f"engineering.gates.{gate_id}",
        path=plan.source_path,
    )


def find_gate_definition(plan: Plan, gate_id: str) -> dict[str, Any]:
    """Return one gate definition for CLI/runner adapters."""
    return _gate_definition(plan, gate_id)


def record_gate_result(
    root: str | Path,
    plans_dir: str | Path,
    plan_id: str,
    *,
    gate_id: str,
    outcome: str,
    actor: str,
    evidence_kind: str,
    expected_revision: int | None = None,
    batch: str | None = None,
    output_digest: str | None = None,
    artifact: str | None = None,
    reason: str | None = None,
) -> WorkflowResult:
    """Record durable evidence for one gate; never infer command execution."""
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, Path(plans_dir))
    plan = find_plan(plan_id, directory, root=root_path)
    _require_execution_ready(plan, expected_revision=expected_revision, actor=actor)
    definition = _gate_definition(plan, gate_id)
    if outcome not in {"passed", "failed", "not-run"}:
        raise PlanError("GATE_OUTCOME_INVALID", f"Invalid gate outcome: {outcome}", field="outcome", path=plan.source_path)
    if evidence_kind not in {"runner", "external", "review"}:
        raise PlanError("GATE_EVIDENCE_KIND_INVALID", f"Invalid gate evidence kind: {evidence_kind}", field="evidence_kind", path=plan.source_path)

    definition_kind = str(definition.get("kind", "command"))
    if definition_kind == "command" and evidence_kind == "review":
        raise PlanError("GATE_KIND_INVALID", f"Command gate {gate_id} cannot be satisfied by review.", field=f"engineering.gates.{gate_id}", path=plan.source_path)
    if definition_kind in {"review", "manual"} and evidence_kind != "review":
        raise PlanError("GATE_KIND_INVALID", f"Review gate {gate_id} requires review evidence.", field=f"engineering.gates.{gate_id}", path=plan.source_path)
    if evidence_kind == "runner" and not output_digest:
        raise PlanError("GATE_EVIDENCE_INVALID", f"Runner evidence for {gate_id} requires an output digest.", field="output_digest", path=plan.source_path)
    if evidence_kind in {"external", "review"} and not artifact:
        raise PlanError("GATE_EVIDENCE_INVALID", f"{evidence_kind.title()} evidence for {gate_id} requires an artifact.", field="artifact", path=plan.source_path)
    if outcome in {"failed", "not-run"} and not reason:
        raise PlanError("GATE_EVIDENCE_INVALID", f"A {outcome} gate result requires a reason.", field="reason", path=plan.source_path)

    input_fingerprint = None
    if batch:
        _batch_row(plan, batch)
        input_fingerprint = fingerprint_batch_inputs(root_path, plan, batch)["fingerprint"]

    payload = {
        "at": _iso_now(),
        "actor": actor,
        "artifact": artifact,
        "evidence_kind": evidence_kind,
        "gate_definition_hash": _sha256_json(definition),
        "gate_id": gate_id,
        "batch": batch,
        "input_fingerprint": input_fingerprint,
        "outcome": outcome,
        "output_digest": output_digest,
        "plan_revision": int(plan.frontmatter["revision"]),
        "reason": reason,
    }
    plan.frontmatter["gate_results"] = [*plan.frontmatter.get("gate_results", []), payload]
    return _commit_state_revision(
        root_path,
        directory,
        plan,
        event="gate_recorded",
        actor=actor,
        reason=f"{gate_id}: {outcome}",
    )


def _require_test_contract(plan: Plan, batch: str, root: Path) -> None:
    root_path = root.resolve()
    tests = plan.frontmatter.get("testing", {}).get("tests", [])
    for test in tests:
        if not isinstance(test, dict) or str(test.get("batch", "")) != batch or test.get("disposition") not in {"implement", "reuse"}:
            continue
        references = test.get("files", [])
        if not references:
            raise PlanError(
                "TEST_CONTRACT_MISMATCH",
                f"Batch {batch} test {test.get('test_id')} has no file reference.",
                field=f"testing.tests.{test.get('test_id')}.files",
                path=plan.source_path,
            )
        relative = str(references[0]).split("::", 1)[0]
        path = (root_path / relative).resolve()
        if not path.is_file() or not path.is_relative_to(root_path):
            raise PlanError(
                "TEST_CONTRACT_MISMATCH",
                f"Batch {batch} test file does not exist: {relative}",
                field=f"testing.tests.{test.get('test_id')}.files",
                path=plan.source_path,
            )
