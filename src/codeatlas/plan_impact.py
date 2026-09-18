from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .plans import PlanError, find_plan, is_plan_file, parse_plan
from .storage import Store

OPEN_PLAN_STATUSES = {"approved", "executing", "blocked"}
DEFAULT_MAX_ITEMS = 200
DEFAULT_MAX_GRAPH_DEPTH = 2
DEFAULT_MAX_GRAPH_NODES = 256
DEFAULT_MAX_POSSIBLE = 12
DEFAULT_MAX_PLANS = 200


def _plans_dir(root: Path, plans_dir: str | Path) -> Path:
    directory = Path(plans_dir)
    if not directory.is_absolute():
        directory = root / directory
    resolved = directory.resolve()
    if resolved != root and root not in resolved.parents:
        raise PlanError("PLAN_OUTSIDE_ROOT", "Plans directory is outside the project root.")
    return resolved


def _normalise_changed_files(values: list[str] | None) -> list[str]:
    changed: set[str] = set()
    for value in values or []:
        raw = str(value).strip().replace("\\", "/")
        if raw:
            changed.add(raw.rstrip("/"))
    return sorted(changed)


def _normalise_changed_symbols(values: list[str] | None) -> list[str]:
    return sorted({str(value).strip() for value in values or [] if str(value).strip()})


def _lexical_tokens(value: str) -> set[str]:
    return {
        part
        for part in re.split(r"[^a-z0-9_]+", value.casefold())
        if len(part) >= 3
    }


def _planned_symbols(plan: Any) -> list[dict[str, Any]]:
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    task_refs: set[str] = set()
    for task in plan.tasks:
        batch = str(task.get("batch", "")).strip() or "unassigned"
        for ref in task.get("symbols", []):
            task_refs.add(str(ref))
            key = (str(ref), batch)
            entries.setdefault(
                key,
                {"batch": batch, "ref": str(ref), "task": task.get("number")},
            )
    for ref in plan.frontmatter.get("symbols", []):
        if not str(ref).strip():
            continue
        if str(ref) in task_refs:
            continue
        key = (str(ref), "unassigned")
        entries.setdefault(key, {"batch": "unassigned", "ref": str(ref), "task": None})
    return sorted(entries.values(), key=lambda item: (item["batch"], item["ref"]))


def _planned_files(plan: Any) -> list[dict[str, Any]]:
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for task in plan.tasks:
        batch = str(task.get("batch", "")).strip() or "unassigned"
        for ref in task.get("files", []):
            key = (str(ref), batch)
            entries.setdefault(
                key,
                {"batch": batch, "ref": str(ref), "task": task.get("number")},
            )
    for ref in plan.frontmatter.get("files", []):
        if not str(ref).strip():
            continue
        key = (str(ref), "unassigned")
        entries.setdefault(key, {"batch": "unassigned", "ref": str(ref), "task": None})
    return sorted(entries.values(), key=lambda item: (item["batch"], item["ref"]))


def _symbol_source_path(
    store: Store | None,
    ref: str,
    source_by_symbol: dict[str, str],
) -> str:
    if ref in source_by_symbol:
        return source_by_symbol[ref]
    if store is None:
        return ""
    row = store.symbol_row(ref)
    return str(row[0]).replace("\\", "/") if row else ""


def compute_update_impact(
    root: str | Path,
    *,
    changed_files: list[str] | None = None,
    changed_symbols: list[str] | None = None,
    source_paths_by_symbol: dict[str, str] | None = None,
    plans_dir: str | Path = "docs/plans",
    max_items: int = DEFAULT_MAX_ITEMS,
    max_plans: int = DEFAULT_MAX_PLANS,
) -> dict[str, Any]:
    """Compute bounded impact across all plans after an update.

    Malformed plans become structured warnings; one bad plan must not hide
    the report for every valid plan.
    """
    if max_items <= 0 or max_plans <= 0:
        raise PlanError("PLAN_IMPACT_LIMIT_INVALID", "Limits must be greater than zero.")
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, plans_dir)
    warnings: list[dict[str, Any]] = []
    affected_plans: list[dict[str, Any]] = []
    total_plans = 0
    truncated = False

    if not directory.is_dir():
        warnings.append(
            {
                "code": "PLANS_DIRECTORY_NOT_FOUND",
                "message": f"Plans directory does not exist: {directory}",
                "path": directory.as_posix(),
            }
        )
        directory.mkdir(parents=True, exist_ok=True)

    for path in sorted(directory.glob("*.md")):
        if not is_plan_file(path):
            continue
        if total_plans >= max_plans:
            truncated = True
            break
        total_plans += 1
        try:
            plan = parse_plan(path, root=root_path)
        except PlanError as exc:
            warnings.append(
                {"code": exc.code, "message": exc.message, "path": exc.path}
            )
            continue
        try:
            payload = compute_plan_impact(
                root_path,
                plan.id,
                changed_files=changed_files,
                changed_symbols=changed_symbols,
                source_paths_by_symbol=source_paths_by_symbol,
                plans_dir=directory,
                max_items=max_items,
                use_index=True,
            )
        except PlanError as exc:
            warnings.append(
                {"code": exc.code, "message": exc.message, "path": plan.source_path}
            )
            continue
        if payload["items"]:
            affected_plans.append(
                {
                    "affected_batches": payload["affected_batches"],
                    "items": payload["items"],
                    "plan_id": payload["plan_id"],
                    "plan_revision": payload["plan_revision"],
                    "plan_status": payload["plan_status"],
                    "warnings": payload["warnings"],
                }
            )

    affected_plans.sort(key=lambda item: str(item["plan_id"]))
    warnings.sort(key=lambda item: (str(item["code"]), str(item["message"]), str(item.get("path", ""))))
    return {
        "affected_plans": affected_plans,
        "changed_files": _normalise_changed_files(changed_files),
        "changed_symbols": _normalise_changed_symbols(changed_symbols),
        "plan_count": total_plans,
        "schema_version": 1,
        "truncated": truncated,
        "warnings": warnings,
    }


def write_update_impact_report(
    root: str | Path,
    *,
    changed_files: list[str] | None = None,
    changed_symbols: list[str] | None = None,
    source_paths_by_symbol: dict[str, str] | None = None,
    plans_dir: str | Path = "docs/plans",
    max_items: int = DEFAULT_MAX_ITEMS,
    max_plans: int = DEFAULT_MAX_PLANS,
) -> Path:
    """Write a derived, rebuildable impact report under `.codeatlas/plans/`."""
    root_path = Path(root).resolve()
    payload = compute_update_impact(
        root_path,
        changed_files=changed_files,
        changed_symbols=changed_symbols,
        source_paths_by_symbol=source_paths_by_symbol,
        plans_dir=plans_dir,
        max_items=max_items,
        max_plans=max_plans,
    )
    payload["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    destination = root_path / ".codeatlas" / "plans" / "impact-report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def compute_plan_impact(
    root: str | Path,
    plan_id: str,
    *,
    changed_files: list[str] | None = None,
    changed_symbols: list[str] | None = None,
    source_paths_by_symbol: dict[str, str] | None = None,
    plans_dir: str | Path = "docs/plans",
    max_items: int = DEFAULT_MAX_ITEMS,
    use_index: bool = False,
    max_graph_depth: int = DEFAULT_MAX_GRAPH_DEPTH,
    max_graph_nodes: int = DEFAULT_MAX_GRAPH_NODES,
    max_possible: int = DEFAULT_MAX_POSSIBLE,
) -> dict[str, Any]:
    """Compute bounded direct, indirect, and possible impact for one plan.

    Direct matching is always available without an index. Index-backed graph
    and lexical impact are opt-in so the core surface remains deterministic
    and useful for lightweight plan matching.
    """
    if max_items <= 0 or max_graph_nodes <= 0 or max_possible <= 0:
        raise PlanError("PLAN_IMPACT_LIMIT_INVALID", "max_items must be greater than zero.")
    if max_graph_depth < 0:
        raise PlanError("PLAN_IMPACT_LIMIT_INVALID", "max_graph_depth cannot be negative.")
    root_path = Path(root).resolve()
    directory = _plans_dir(root_path, plans_dir)
    plan = find_plan(plan_id, directory, root=root_path)

    warnings: list[dict[str, str]] = []
    if plan.status not in OPEN_PLAN_STATUSES:
        warnings.append(
            {
                "code": "PLAN_NOT_OPEN",
                "message": "Done plans are excluded from new impact work.",
            }
        )

    files = _normalise_changed_files(changed_files)
    symbols = _normalise_changed_symbols(changed_symbols)
    source_by_symbol = {
        str(key).strip(): str(value).strip().replace("\\", "/")
        for key, value in (source_paths_by_symbol or {}).items()
        if str(key).strip() and str(value).strip()
    }

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    store: Store | None = None
    index_available = False
    if use_index:
        db_path = root_path / ".codeatlas" / "state.db"
        if db_path.is_file():
            store = Store(db_path)
            index_available = True
        else:
            warnings.append(
                {
                    "code": "INDEX_NOT_FOUND",
                    "message": "No index is available for indirect or possible impact.",
                }
            )

    try:
        if plan.status in OPEN_PLAN_STATUSES:
            for task in plan.tasks:
                batch = str(task.get("batch", "")).strip() or "unassigned"
                task_number = task.get("number")
                for changed in files:
                    if changed not in {str(value) for value in task.get("files", [])}:
                        continue
                    key = ("file", batch, changed)
                    if key not in seen:
                        seen.add(key)
                        items.append(
                            {
                                "batch": batch,
                                "confidence": 1.0,
                                "kind": "file",
                                "level": "direct",
                                "ref": changed,
                                "source_path": changed,
                                "task": task_number,
                            }
                        )
                for changed in symbols:
                    if changed not in {str(value) for value in task.get("symbols", [])}:
                        continue
                    source_path = _symbol_source_path(store, changed, source_by_symbol)
                    key = ("symbol", batch, changed)
                    if key not in seen:
                        seen.add(key)
                        items.append(
                            {
                                "batch": batch,
                                "confidence": 1.0,
                                "kind": "symbol",
                                "level": "direct",
                                "ref": changed,
                                "source_path": source_path,
                                "task": task_number,
                            }
                        )

            if store is not None and max_graph_depth > 0:
                planned = {item["ref"]: item for item in _planned_symbols(plan)}
                graph_roots = set(symbols)
                for changed in files:
                    for row in store.symbols_for_file(changed)[:max_graph_nodes]:
                        graph_roots.add(str(row[1]))
                queue: list[tuple[str, int]] = [(ref, 0) for ref in sorted(graph_roots)]
                visited = set(graph_roots)
                while queue:
                    current, depth = queue.pop(0)
                    if depth >= max_graph_depth:
                        continue
                    neighbours: list[tuple[str, str]] = []
                    for direction, refs in (
                        ("caller", store.callers_of(current)),
                        ("callee", store.callees_of(current)),
                    ):
                        for neighbour in refs[:max_graph_nodes]:
                            neighbours.append((direction, str(neighbour)))
                    for direction, neighbour in sorted(neighbours):
                        if neighbour in visited:
                            continue
                        visited.add(neighbour)
                        if len(visited) > max_graph_nodes:
                            continue
                        planned_item = planned.get(neighbour)
                        if planned_item is not None:
                            key = ("indirect", neighbour, current)
                            if key not in seen:
                                seen.add(key)
                                items.append(
                                    {
                                        "batch": planned_item["batch"],
                                        "changed_ref": current,
                                        "confidence": max(0.35, 1.0 - 0.15 * (depth + 1)),
                                        "direction": direction,
                                        "graph_depth": depth + 1,
                                        "kind": "symbol",
                                        "level": "indirect",
                                        "ref": neighbour,
                                        "source_path": _symbol_source_path(
                                            store, neighbour, source_by_symbol
                                        ),
                                        "task": planned_item["task"],
                                    }
                                )
                            continue
                        queue.append((neighbour, depth + 1))

            direct_refs = {
                str(item["ref"])
                for item in items
                if item["level"] == "direct"
            }
            possible_count = 0
            changed_tokens: dict[str, set[str]] = {
                ref: _lexical_tokens(ref) for ref in symbols
            }
            for planned_item in _planned_symbols(plan):
                if possible_count >= max_possible:
                    break
                ref = str(planned_item["ref"])
                if ref in direct_refs:
                    continue
                planned_tokens = _lexical_tokens(ref)
                for changed, tokens in changed_tokens.items():
                    overlap = sorted(planned_tokens & tokens)
                    if not overlap:
                        continue
                    key = ("possible", ref, changed)
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(
                        {
                            "batch": planned_item["batch"],
                            "changed_ref": changed,
                            "confidence": 0.55,
                            "kind": "symbol",
                            "level": "possible",
                            "reason": "lexical overlap: " + ", ".join(overlap),
                            "ref": ref,
                            "source_path": _symbol_source_path(
                                store, ref, source_by_symbol
                            ),
                            "task": planned_item["task"],
                        }
                    )
                    possible_count += 1
                    break

            planned_files = _planned_files(plan)
            for changed in files:
                if possible_count >= max_possible:
                    break
                changed_name = Path(changed).name
                for planned_item in planned_files:
                    ref = str(planned_item["ref"])
                    if ref == changed or Path(ref).name != changed_name:
                        continue
                    key = ("possible", ref, changed)
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(
                        {
                            "batch": planned_item["batch"],
                            "changed_ref": changed,
                            "confidence": 0.5,
                            "kind": "file",
                            "level": "possible",
                            "reason": "same file basename in a different path",
                            "ref": ref,
                            "source_path": ref,
                            "task": planned_item["task"],
                        }
                    )
                    possible_count += 1
                    break

        items.sort(
            key=lambda item: (
                str(item["level"]),
                str(item["batch"]),
                str(item["kind"]),
                str(item["ref"]),
            )
        )
        truncated = len(items) > max_items
        items = items[:max_items]
        affected_batches = sorted({str(item["batch"]) for item in items})
        warnings.sort(key=lambda item: (item["code"], item["message"]))
        return {
            "affected_batches": affected_batches,
            "index_available": index_available,
            "items": items,
            "limits": {
                "max_graph_depth": max_graph_depth,
                "max_graph_nodes": max_graph_nodes,
                "max_items": max_items,
                "max_possible": max_possible,
            },
            "plan_id": plan.id,
            "plan_revision": int(plan.frontmatter["revision"]),
            "plan_status": plan.status,
            "schema_version": 1,
            "truncated": truncated,
            "warnings": warnings,
        }
    finally:
        if store is not None:
            store.close()
