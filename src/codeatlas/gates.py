"""Trusted execution adapter for configured plan quality gates."""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path
from typing import Any

from .plans import PlanError


GATE_OUTPUT_LIMIT = 20_000


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def run_gate(
    gate: dict[str, Any],
    *,
    root: str | Path = ".",
    timeout_seconds: float = 60,
) -> dict[str, Any]:
    """Run one configured argv gate without shell interpolation."""
    gate_id = str(gate.get("id", "")).strip()
    if not gate_id:
        raise PlanError("GATE_DEFINITION_INVALID", "Gate is missing an ID.", field="engineering.gates.id")
    if gate.get("kind") != "command":
        raise PlanError("GATE_KIND_INVALID", f"Gate {gate_id} is not a command gate.", field=f"engineering.gates.{gate_id}.kind")
    command = gate.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise PlanError(
            "GATE_COMMAND_INVALID",
            f"Gate {gate_id} must define a non-empty argv list.",
            field=f"engineering.gates.{gate_id}.command",
        )

    root_path = Path(root).resolve()
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=root_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "gate_id": gate_id,
            "outcome": "not-run",
            "exit_code": None,
            "output_digest": _sha256_text(str(exc)),
            "output_excerpt": str(exc)[:GATE_OUTPUT_LIMIT],
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "reason": "command-not-found",
        }
    except subprocess.TimeoutExpired:
        return {
            "gate_id": gate_id,
            "outcome": "failed",
            "exit_code": None,
            "output_digest": _sha256_text(f"timeout after {timeout_seconds} seconds"),
            "output_excerpt": f"Gate timed out after {timeout_seconds} seconds.",
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "reason": "timeout",
        }

    combined_output = (completed.stdout or "") + (completed.stderr or "")
    return {
        "gate_id": gate_id,
        "outcome": "passed" if completed.returncode == 0 else "failed",
        "exit_code": completed.returncode,
        "output_digest": _sha256_text(combined_output),
        "output_excerpt": combined_output[:GATE_OUTPUT_LIMIT],
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "reason": None,
    }
