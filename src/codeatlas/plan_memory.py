"""Derived plan memory: input fingerprints, stale evidence, and doctor checks.

This module reads plans and referenced inputs. It never rewrites plan files;
state changes remain in `plan_workflow.py`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .plans import Plan, PlanError, is_plan_file, lint_plans, parse_plan, plan_graph
from .storage import Store


ACTIVE_PLAN_STATUSES = {"draft", "approved", "executing", "blocked"}


def load_plan_state_config(root: str | Path) -> dict[str, Any]:
    """Load the explicit update-time plan-state write authority for one project."""
    root_path = Path(root).resolve()
    config_path = root_path / "codeatlas.config.json"
    if not config_path.is_file():
        return {"allow_update_plan_state": True}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PlanError(
            "PLAN_CONFIG_INVALID",
            f"Could not read project configuration: {exc}",
            path=config_path.as_posix(),
        ) from exc
    if not isinstance(payload, dict):
        raise PlanError(
            "PLAN_CONFIG_INVALID",
            "Project configuration must be a JSON object.",
            path=config_path.as_posix(),
        )
    if "allow_update_plan_state" in payload:
        value = payload["allow_update_plan_state"]
        if not isinstance(value, bool):
            raise PlanError(
                "PLAN_CONFIG_INVALID",
                "allow_update_plan_state must be a boolean.",
                field="allow_update_plan_state",
                path=config_path.as_posix(),
            )
        allowed = value
    else:
        allowed = True
    return {"allow_update_plan_state": allowed}


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _inside_root(root: Path, value: str) -> Path:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise PlanError("PLAN_OUTSIDE_ROOT", f"Plan references a path outside the project root: {value}", field="files")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise PlanError("PLAN_OUTSIDE_ROOT", f"Plan references a path outside the project root: {value}", field="files")
    return resolved


def _relative_file_hashes(root: Path, paths: set[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for value in sorted(paths):
        path = _inside_root(root, value)
        digest = "missing"
        if path.is_file():
            digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        items.append({"path": value, "content_hash": digest})
    return items


def _referenced_paths(plan: Plan, batch: str) -> set[str]:
    paths: set[str] = set()
    for task in plan.tasks:
        if str(task.get("batch", "")) != batch:
            continue
        paths.update(str(item) for item in task.get("files", []))
    tests = plan.frontmatter.get("testing", {}).get("tests", [])
    for test in tests:
        if isinstance(test, dict) and str(test.get("batch", "")) == batch:
            for value in test.get("files", []):
                paths.add(str(value).split("::", 1)[0])
    return paths


def _known_symbols(root: Path) -> set[str] | None:
    """Return indexed qualified names and module paths, or None if unindexed."""
    db = root / ".codeatlas" / "state.db"
    if not db.is_file():
        return None
    store = Store(db)
    try:
        references = {str(row[1]) for row in store.all_symbols()}
        references.update(str(path) for path in store.known_paths())
        return references
    finally:
        store.close()


def _referenced_symbols(plan: Plan, batch: str) -> list[str]:
    symbols: set[str] = set()
    for task in plan.tasks:
        if str(task.get("batch", "")) == batch:
            symbols.update(str(item) for item in task.get("symbols", []))
    return sorted(symbols)


def _relevant_gate_definitions(plan: Plan, batch: str) -> list[dict[str, Any]]:
    engineering = plan.frontmatter.get("engineering", {})
    definitions = {str(item.get("id", "")): item for item in engineering.get("gates", []) if isinstance(item, dict)}
    tests = plan.frontmatter.get("testing", {}).get("tests", [])
    gate_ids = {
        str(test.get("gate_id", ""))
        for test in tests
        if isinstance(test, dict) and str(test.get("batch", "")) == batch and str(test.get("gate_id", "")).strip()
    }
    if not gate_ids:
        gate_ids = {str(item) for item in engineering.get("quality_gates", [])}
    return [definitions[gate_id] for gate_id in sorted(gate_ids) if gate_id in definitions]


def fingerprint_batch_inputs(root: str | Path, plan: Plan, batch: str) -> dict[str, Any]:
    """Return a bounded, stable fingerprint for one batch's declared inputs."""
    root_path = Path(root).resolve()
    paths = _referenced_paths(plan, batch)
    files = _relative_file_hashes(root_path, paths)
    payload = {
        "batch": batch,
        "files": files,
        "gate_definitions": _relevant_gate_definitions(plan, batch),
        "symbols": _referenced_symbols(plan, batch),
    }
    return {
        "plan_id": plan.id,
        "plan_revision": int(plan.frontmatter["revision"]),
        **payload,
        "fingerprint": _sha256_json(payload),
    }


def detect_stale_evidence(
    root: str | Path,
    plans_dir: str | Path,
    *,
    include_all: bool = False,
) -> dict[str, Any]:
    """Detect stale evidence for active plans by default.

    Set ``include_all`` to include historical done, cancelled, and archived
    plans for audit-only inspection; this function never rewrites evidence.
    """
    root_path = Path(root).resolve()
    directory = Path(plans_dir)
    if not directory.is_absolute():
        directory = root_path / directory
    items: list[dict[str, Any]] = []
    unknown = 0
    errors: list[dict[str, str]] = []
    if not directory.is_dir():
        return {"schema_version": 1, "items": [], "unknown_count": 0, "errors": []}

    for path in sorted(directory.glob("*.md")):
        if not is_plan_file(path):
            continue
        try:
            plan = parse_plan(path, root=root_path)
        except PlanError as exc:
            errors.append({"code": exc.code, "message": exc.message, "path": path.as_posix()})
            continue
        if not include_all and plan.status not in ACTIVE_PLAN_STATUSES:
            continue
        latest_results: dict[tuple[str, str], dict] = {}
        for result in plan.frontmatter.get("gate_results", []):
            if not isinstance(result, dict):
                continue
            batch = str(result.get("batch", "")).strip()
            gate_id = str(result.get("gate_id", "")).strip()
            if not batch:
                unknown += 1
                continue
            latest_results[(batch, gate_id)] = result
        for (batch, _gate_id), result in sorted(latest_results.items()):
            recorded = str(result.get("input_fingerprint", "")).strip()
            if not batch or not recorded:
                unknown += 1
                continue
            try:
                current = fingerprint_batch_inputs(root_path, plan, batch)["fingerprint"]
            except PlanError as exc:
                errors.append({"code": exc.code, "message": exc.message, "path": plan.source_path})
                continue
            if current != recorded:
                items.append(
                    {
                        "plan_id": plan.id,
                        "batch": batch,
                        "gate_id": str(result.get("gate_id", "")),
                        "recorded_fingerprint": recorded,
                        "current_fingerprint": current,
                        "plan_revision": int(plan.frontmatter["revision"]),
                    }
                )
    return {
        "schema_version": 1,
        "scope": "all" if include_all else "active",
        "items": items,
        "unknown_count": unknown,
        "errors": errors,
    }


def write_stale_report(root: str | Path, plans_dir: str | Path) -> Path | None:
    """Write a bounded report under `.codeatlas/plans/`; plans remain untouched."""
    root_path = Path(root).resolve()
    directory = Path(plans_dir)
    if not directory.is_absolute():
        directory = root_path / directory
    if not directory.is_dir():
        return None
    report = detect_stale_evidence(root_path, directory)
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    destination = root_path / ".codeatlas" / "plans" / "stale-report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def plan_doctor_problems(root: str | Path, plans_dir: str | Path) -> list[str]:
    """Check plan lint, dependency cycles, and projection drift."""
    root_path = Path(root).resolve()
    directory = Path(plans_dir)
    if not directory.is_absolute():
        directory = root_path / directory
    if not directory.is_dir():
        return []

    problems: list[str] = []
    issues = lint_plans(directory, root=root_path)
    for issue in issues:
        location = f" [{issue.path}]" if issue.path else ""
        problems.append(f"plan lint{location}: {issue.code}: {issue.message}")

    for path in sorted(directory.glob("*.md")):
        if not is_plan_file(path):
            continue
        try:
            plan = parse_plan(path, root=root_path)
        except PlanError:
            continue
        for result in plan.frontmatter.get("gate_results", []):
            if not isinstance(result, dict):
                continue
            batch_value = result.get("batch")
            fingerprint_value = result.get("input_fingerprint")
            batch = "" if batch_value is None else str(batch_value).strip()
            fingerprint = "" if fingerprint_value is None else str(fingerprint_value).strip()
            gate_id = str(result.get("gate_id", "")).strip()
            if not batch:
                problems.append(f"plan gate evidence missing batch: {plan.id} {gate_id}")
            elif not fingerprint:
                problems.append(f"plan gate evidence missing fingerprint: {plan.id} {gate_id}")
        derived = plan_graph(plan)
        if derived["cycle_detected"]:
            problems.append(f"plan graph cycle: {plan.id}")
        projection = root_path / ".codeatlas" / "plans" / f"{plan.id}.json"
        if not projection.is_file():
            continue
        try:
            payload = json.loads(projection.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            problems.append(f"plan projection unreadable: {plan.id}")
            continue
        expected = {
            "id": plan.id,
            "status": plan.status,
            "revision": int(plan.frontmatter["revision"]),
            "content_hash": plan.frontmatter.get("content_hash"),
            "source_path": plan.source_path,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            problems.append(f"plan projection drift: {plan.id}")
    return problems


def plan_doctor_warnings(root: str | Path, plans_dir: str | Path) -> list[str]:
    """Return active-plan and legacy-file warnings for doctor.

    EN: historical plan evidence remains on disk but does not create a current
    unresolved-symbol signal. ZH: 历史计划证据保留在磁盘上，但不再生成当前
    的 unresolved-symbol 噪声。
    """
    root_path = Path(root).resolve()
    directory = Path(plans_dir)
    if not directory.is_absolute():
        directory = root_path / directory
    if not directory.is_dir():
        return []
    warnings: list[str] = []
    known_symbols = _known_symbols(root_path)
    for path in sorted(directory.glob("*.md")):
        if known_symbols is not None and is_plan_file(path):
            try:
                plan = parse_plan(path, root=root_path)
            except PlanError:
                pass
            else:
                if plan.status not in ACTIVE_PLAN_STATUSES:
                    continue
                referenced_symbols = {
                    str(ref).strip()
                    for ref in plan.frontmatter.get("symbols", [])
                    if str(ref).strip()
                }
                for task in plan.tasks:
                    referenced_symbols.update(
                        str(ref).strip() for ref in task.get("symbols", []) if str(ref).strip()
                    )
                for ref in sorted(referenced_symbols):
                    dotted_path = ref.replace(".", "/")
                    suffixes = {f"/{dotted_path}.py", f"/{dotted_path}/__init__.py"}
                    resolves = ref in known_symbols or any(
                        path_str == f"{dotted_path}.py"
                        or path_str == f"{dotted_path}/__init__.py"
                        or path_str.endswith(tuple(suffixes))
                        for path_str in known_symbols
                        if "/" in path_str
                    ) or any(
                        qualified.endswith(f".{ref}")
                        for qualified in known_symbols
                        if "/" not in qualified
                    )
                    if not resolves:
                        warnings.append(f"plan unresolved symbol: {plan.id}: {ref}")
        if not is_plan_file(path):
            relative = path.relative_to(root_path).as_posix()
            warnings.append(f"non-plan markdown retained in plans directory: {relative}")
    return warnings
