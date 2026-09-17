---
name: plan-artifacts
description: Use CodeAtlas durable plan artifacts to create, approve, execute, inspect, and resume an implementation task in this repository.
metadata:
  short-description: Drive the CodeAtlas plan workflow
---

# CodeAtlas plan artifacts

Use this skill for non-trivial implementation tasks that need a durable plan, validated batches, or resumable state. Read `CODEATLAS.md` before deciding where to change code. Do not use this skill as a replacement for CodeAtlas evidence or as a second source of plan truth.

## Workflow

1. Check existing plans with `codeatlas plan status --json` and `codeatlas plan lint <root> --json`.
2. Create a plan with `codeatlas plan new <slug> <root> --json`. Fill in the goal, non-goals, tasks, batches, test contract, engineering profile, and quality gates.
3. Let a human record approval with `codeatlas plan approve <plan-id> <root> --approved-by "Human Name" --json`.
4. Execute one batch at a time with `plan batch start`, run the applicable gates, then `plan batch complete`.
5. Inspect bounded views with `plan show --view execution`, `engineering`, `evidence`, or `graph` instead of loading the full Markdown body.
6. After code changes, run `codeatlas update .` and `codeatlas plan stale <root> --json`. If recorded evidence no longer applies, mark the batch stale with `plan batch stale`; never pretend old evidence still passes.
7. Before finishing, run `codeatlas update .`, `codeatlas doctor`, and the plan's validation commands.

## Constraints

- Markdown in `docs/plans/` is authoritative; `.codeatlas/plans/*.json` and snapshots are derived or audit artifacts.
- Do not self-approve a plan. A conversational approval is not a durable approval.
- Do not parse hand-written diagrams as plan state. Render graphs from structured task and batch tables.
- Do not rewrite plans from `codeatlas update`; it reports stale evidence, but plan mutations go through the workflow commands.
- Stop and report options when validation fails, a required approval is missing, or a batch would exceed the plan's change-control limits.
