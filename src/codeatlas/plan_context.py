"""Deterministic, bounded plan-context retrieval over the CodeAtlas index."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import Store


DEFAULT_MAX_EVIDENCE = 8
DEFAULT_MAX_TOKENS = 4_000
_CONVENTION_FILES = (
    "AGENTS.md",
    "README.md",
    "README.zh-CN.md",
    "CODEATLAS.md",
    "docs/plan-contract.md",
)
_STOP_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "add", "make",
    "using", "use", "should", "must", "have", "has", "are", "was", "were",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tokens(query: str) -> list[str]:
    return [item for item in re.findall(r"[A-Za-z0-9_\\-]{3,}", query) if item.casefold() not in _STOP_WORDS]


def _file_hash(root: Path, path: str) -> str | None:
    try:
        return "sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest()
    except OSError:
        return None


def _bootstrap(root: Path, query: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "bootstrap_required",
        "error_code": "NO_INDEX",
        "query": query,
        "generated_at": _utc_now(),
        "index_version": None,
        "summary": "No CodeAtlas index is available for this project.",
        "hint": "Run `codeatlas scan .` to create the index, then retry plan context.",
        "evidence": [],
        "suggested_pages": [],
        "engineering": {
            "suggested_profile": "product",
            "applicable_gates": ["unit-tests"],
            "architecture_boundaries": [],
        },
        "impact_scope": {"files": [], "symbols": []},
        "tokens": 0,
        "truncated": False,
        "reasons": [reason],
    }


def _rank_key(symbol: dict[str, Any], terms: list[str]) -> tuple[int, int, str, str]:
    qname = str(symbol.get("qualified_name", ""))
    path = str(symbol.get("file", ""))
    name = qname.rsplit(".", 1)[-1].casefold()
    exact = 0 if any(term.casefold() == name for term in terms) else 1
    return exact, len(qname), path, qname


def _confidence(symbol: dict[str, Any], terms: list[str]) -> float:
    qname = str(symbol.get("qualified_name", ""))
    name = qname.rsplit(".", 1)[-1].casefold()
    description = str(symbol.get("description", "")).casefold()
    if any(term.casefold() == name for term in terms):
        return 0.95
    if any(term.casefold() in name for term in terms):
        return 0.85
    if any(term.casefold() in description for term in terms):
        return 0.7
    return 0.6


def retrieve_plan_context(
    root: str | Path,
    query: str,
    *,
    max_evidence: int = DEFAULT_MAX_EVIDENCE,
    max_neighbors: int = 2,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Retrieve a bounded evidence bundle for planning; no LLM is required."""
    root_path = Path(root).resolve()
    db = root_path / ".codeatlas" / "state.db"
    if not db.is_file():
        return _bootstrap(root_path, query, "no index")
    if not query.strip():
        return _bootstrap(root_path, query, "empty query")

    terms = _tokens(query)
    matched: dict[str, dict[str, Any]] = {}
    try:
        from .service import search_symbols

        for term in terms:
            for row in search_symbols(root_path, term, limit=max_evidence * 3):
                matched[str(row["qualified_name"])] = row
    except FileNotFoundError:
        return _bootstrap(root_path, query, "index disappeared during retrieval")

    ranked = sorted(matched.values(), key=lambda row: _rank_key(row, terms))[:max_evidence]
    store = Store(db)
    neighbours: list[tuple[dict[str, Any], str, str]] = []
    try:
        file_hashes = store.get_all_file_hashes()
        index_version = store.index_version()
        for row in ranked:
            qname = str(row["qualified_name"])
            for direction, values in (
                ("caller", store.callers_of(qname)),
                ("callee", store.callees_of(qname)),
            ):
                for neighbour in values[:max_neighbors]:
                    if neighbour in matched:
                        continue
                    symbol = store.symbol_row(neighbour)
                    if symbol:
                        neighbours.append(
                            (
                                {
                                    "file": symbol[0],
                                    "qualified_name": symbol[1],
                                    "line": symbol[8],
                                    "signature": symbol[4],
                                    "description": "",
                                },
                                qname,
                                direction,
                            )
                        )
    finally:
        store.close()

    evidence: list[dict[str, Any]] = []
    for index, row in enumerate(ranked):
        source_path = str(row["file"])
        indexed_hash = file_hashes.get(source_path)
        current_hash = _file_hash(root_path, source_path)
        stale = current_hash is None or (indexed_hash is not None and indexed_hash != current_hash.removeprefix("sha256:"))
        evidence.append(
            {
                "evidence_id": f"ev-{index + 1:04d}",
                "kind": "symbol",
                "ref": row["qualified_name"],
                "reason": f"Matched query term(s): {', '.join(terms) or query.strip()}",
                "confidence": _confidence(row, terms),
                "stale": stale,
                "source_path": source_path,
                "line": row["line"],
                "signature": row["signature"],
                "description": row["description"],
            }
        )

    for row, source_qname, direction in neighbours:
        if len(evidence) >= max_evidence:
            break
        source_path = str(row["file"])
        indexed_hash = file_hashes.get(source_path)
        current_hash = _file_hash(root_path, source_path)
        stale = current_hash is None or (indexed_hash is not None and indexed_hash != current_hash.removeprefix("sha256:"))
        evidence.append(
            {
                "evidence_id": f"ev-{len(evidence) + 1:04d}",
                "kind": "call-neighbor",
                "ref": row["qualified_name"],
                "reason": f"Call-graph {direction} of {source_qname}",
                "confidence": 0.65,
                "stale": stale,
                "source_path": source_path,
                "line": row["line"],
                "signature": row["signature"],
                "description": row["description"],
            }
        )

    for convention in _convention_evidence(root_path, terms):
        if len(evidence) >= max_evidence:
            break
        evidence.append(
            {
                "evidence_id": f"ev-{len(evidence) + 1:04d}",
                "kind": "convention",
                "ref": convention["path"],
                "reason": convention["reason"],
                "confidence": 0.55,
                "stale": False,
                "source_path": convention["path"],
                "line": convention["line"],
                "signature": "",
                "description": convention["excerpt"],
            }
        )

    suggested_pages = [
        {
            "page_id": item["ref"],
            "granularity": "function",
            "file": item["source_path"],
            "reason": "Top-ranked symbol match",
            "stale": item["stale"],
        }
        for item in evidence[:5]
    ]
    reasons = ["ranked by exact match, shorter qualified name, path, then stable evidence ID"]
    if not evidence:
        reasons.append("no indexed symbol matched the query")

    payload = {
        "schema_version": 1,
        "status": "ok",
        "query": query,
        "generated_at": _utc_now(),
        "index_version": index_version,
        "summary": f"Found {len(evidence)} indexed symbol evidence item(s).",
        "evidence": evidence,
        "suggested_pages": suggested_pages,
        "engineering": _engineering_suggestion(query),
        "impact_scope": {
            "files": sorted({item["source_path"] for item in evidence}),
            "symbols": [item["ref"] for item in evidence],
        },
        "truncated": len(matched) + len(neighbours) > len(evidence),
        "reasons": reasons,
    }
    payload["tokens"] = max(1, len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")) // 4)
    while payload["tokens"] > max_tokens and len(payload["evidence"]) > 1:
        payload["evidence"].pop()
        payload["suggested_pages"] = payload["suggested_pages"][:len(payload["evidence"])]
        payload["impact_scope"]["symbols"] = [item["ref"] for item in payload["evidence"]]
        payload["impact_scope"]["files"] = sorted({item["source_path"] for item in payload["evidence"]})
        payload["truncated"] = True
        if "response reached token cap" not in payload["reasons"]:
            payload["reasons"].append("response reached token cap")
        payload["tokens"] = max(1, len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")) // 4)
    return payload


def _convention_evidence(root_path: Path, terms: list[str], *, max_files: int = 2) -> list[dict[str, str]]:
    if not terms:
        return []
    matches: list[dict[str, str]] = []
    for relative in _CONVENTION_FILES:
        path = root_path / relative
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            lowered = line.casefold()
            if any(term.casefold() in lowered for term in terms):
                matches.append(
                    {
                        "path": relative,
                        "line": str(line_number),
                        "reason": f"Convention text matches query term(s): {', '.join(terms)}",
                        "excerpt": line.strip()[:240],
                    }
                )
                break
        if len(matches) >= max_files:
            break
    return matches


def _engineering_suggestion(query: str) -> dict[str, Any]:
    normalized = query.casefold()
    if any(word in normalized for word in ("auth", "password", "security", "secret", "payment", "token")):
        return {
            "suggested_profile": "production",
            "applicable_gates": ["unit-tests", "security-review", "regression-tests"],
            "architecture_boundaries": ["authentication", "data-access"],
        }
    if any(word in normalized for word in ("api", "contract", "public", "schema")):
        return {
            "suggested_profile": "product",
            "applicable_gates": ["unit-tests", "regression-tests", "public-contract-review"],
            "architecture_boundaries": ["public-api"],
        }
    return {
        "suggested_profile": "product",
        "applicable_gates": ["unit-tests", "regression-tests"],
        "architecture_boundaries": [],
    }
