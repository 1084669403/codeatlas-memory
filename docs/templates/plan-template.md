---
schema_version: 1
id: 2026-09-17-plan-template
title: Plan Template
status: draft
created: 2026-09-17T00:00:00Z
updated_at: 2026-09-17T00:00:00Z
revision: 1
content_hash: pending
revision_type: semantic
reapproval_required: false
owner: human
last_writer: codex
files:
  - docs/templates/plan-template.md
  - tests/test_plan_engine.py
symbols: []
context_pages: []
evidence: []
change_control:
  mode: adaptive
  max_files_per_batch: 3
  max_symbols_per_batch: 8
  require_validation_after_batch: true
engineering:
  profile: product
  architecture_style: modular-monolith
  standards:
    - core-plan-logic-is-tool-agnostic
    - cli-is-adapter-only
    - stable-error-codes-over-prose
  quality_gates:
    - unit-tests
  plain_language: true
  profile_revision: v13-builtins
testing:
  approach: test-with-change
  tests:
    - test_id: T-001
      kind: unit
      behavior: The shipped template satisfies the plan contract and lints clean.
      files:
        - tests/test_plan_engine.py::test_template_fixture_lints_clean
      gate_id: unit-tests
      batch: B1
      task: 1
      disposition: implement
  manual_checks: []
approval: null
---

# Goal

Provide a reusable starting point for validated implementation plans.

# Non-goals

Do not add workflow transitions, rollback, persistence, or MCP tools.

# Tasks

| # | Batch | Task | Depends on | Risk | Files | Symbols | Validation | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | B1 | Replace this row with the first bounded task | none | medium | `docs/templates/plan-template.md` | none | unit-tests gate T-001 | pending |

# Validation

Run the tests listed in the testing contract.

# Testing strategy

Each implementation batch must name the tests or artifacts that prove the task.

# Execution notes

Implement one batch at a time. Stop after validation and record the result.

# Engineering requirements

Keep plan logic tool-agnostic, use stable error codes, and prefer repo-relative POSIX paths.

# Quality gates

unit-tests is blocking.

# Batches

| Batch | Purpose | Depends on | Status | Last validation |
|---|---|---|---|---|
| B1 | First validated batch | none | pending | none |
