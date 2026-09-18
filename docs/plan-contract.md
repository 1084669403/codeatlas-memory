# Plan artifact contract (1a + 1b)

CodeAtlas stores implementation plans as ordinary Markdown files with YAML
frontmatter. The default location is `docs/plans/`. The current surface exposes:

```bash
codeatlas plan new auth-refactor --title "Auth refactor" --json
codeatlas plan show <plan-id> --view summary --json
codeatlas plan status --json
codeatlas plan lint --json
codeatlas plan approve <plan-id> --approved-by "Human Name" --json
codeatlas plan revise <plan-id> --allow-stale --reason "Why" --json
codeatlas plan reapprove <plan-id> --approved-by "Human Name" --json
# First-time migration of a pre-workflow plan (creates revision 0001):
codeatlas plan revise <plan-id> --allow-stale --bootstrap --json
codeatlas plan diff <plan-id> --from-revision 1 --to-revision 2 --json
codeatlas plan batch start <plan-id> B1 --expected-revision 2 --json
codeatlas plan gate run <plan-id> <batch-id> unit-tests --json
codeatlas plan batch complete <plan-id> B1 --expected-revision 5 --json
```

`--plans-dir` can point to another directory relative to the project root.
Plan IDs come from frontmatter and are the stable handle for later workflow
commands. `plan new` never overwrites an existing file.

## Views

- `summary` returns the plan ID, title, status, revision, engineering profile,
  next pending batch, path, and parse warnings.
- `full` additionally returns section names, the task table, and the batch
  table. It does not dump the entire Markdown body.
- `plan status` groups parsed plans by status and reports unreadable files as
  structured warnings.
- `plan lint` returns every finding in one pass. Text output is for humans;
  JSON output is the machine-readable contract.
- `execution` returns the next batch, task rows, validation section, and
  structured testing contract. It does not return the Markdown body.
- `engineering` returns the engineering profile, architecture style, standards,
  quality gates, and engineering requirements without implementation detail.
- `evidence` returns captured evidence and context-page references only.
- `graph` returns a deterministic Mermaid graph rendered from batch/task tables,
  with bounded node/edge limits and explicit cycle/truncation flags.

## Durable workflow

Markdown remains the authoritative source. `plan new` now also records a
canonical content hash, writes the first snapshot under
`docs/plans/revisions/<plan-id>/0001.md`, and appends a creation event to
`events.jsonl`. `plan approve` and `plan revise` continue the same pattern with
numbered snapshots.

`plan diff` compares durable snapshots and reports one dominant classification:

- `semantic`: scope, architecture, task definition, evidence, test contract, or
  engineering contract changed.
- `state`: status, approval, task/batch progress, or other workflow state
  changed.
- `formatting`: only whitespace or formatting changed.

A semantic revision of an approved or executing plan sets
`reapproval_required: true`. Agents still cannot approve their own work: the
CLI records the named human approver and the approval basis, but durable
authorization remains a human responsibility. `plan reapprove` clears that flag
only for an approved or executing plan that actually requires reapproval, and
records a new durable approval decision and revision snapshot.

`plan new` also writes a bounded JSON projection under
`.codeatlas/plans/<plan-id>.json`. Projections contain identity, status,
revision, content hash, and source path. They are rebuildable caches, never the
authoritative plan.

## Execution quality

Batch execution is explicit and durable:

- `plan batch start` records `in-progress` state for a batch and its linked
  tasks, and switches an approved plan to `executing`.
- `plan batch complete` records `passed` only when every required blocking gate
  has passing evidence and the batch's structured test contract resolves.
- Every transition writes a state revision, snapshot, and audit event.

Gate definitions are part of the engineering contract. A command gate uses a
non-empty argv list; plan text cannot become a shell string. `plan gate run`
executes the configured command with the project root as cwd, captures a
bounded output digest/excerpt, records runner evidence, and computes that batch's
input fingerprint. A failed, timed out, unbound, or fingerprint-mismatched
gate cannot make a batch pass.

Review and manual gates require named human evidence and an artifact. Agents may
record review data, but the durable result remains attributable to the actor and
cannot be auto-passed.

Each gate result records the gate ID, batch, outcome, actor, evidence kind,
output digest or artifact, plan revision, batch input fingerprint, and a hash of
the gate definition. ``batch complete`` rejects evidence that is unbound, lacks a
fingerprint, or no longer matches the batch inputs.

Structured test contracts can reference a file, a directory that contains at
least one file, or a project-root-relative glob that matches at least one file.
References are resolved inside the project root; paths or glob matches outside
the root are rejected.

## Memory graph and stale evidence

`plan stale` compares the latest recorded gate evidence for each batch and gate
with the current referenced files, symbols, and gate definitions. Older results
remain in the audit trail but do not determine the current stale signal. It
reports stale evidence as bounded JSON and never changes a plan.
`codeatlas update .` writes `.codeatlas/plans/stale-report.json` with the same
read-only contract. By default, stale detection treats draft, approved,
executing, and blocked plans as current work and treats done, cancelled, and
archived plans as historical evidence. Use `codeatlas plan stale --all` for an
audit view that also includes historical drift; the response marks its scope as
`active` or `all`. Historical evidence is retained and never rewritten.

`codeatlas doctor` also checks plan lint, dependency cycles, and projection
drift. A projection can be rebuilt from Markdown; when the two disagree,
doctor reports the drift instead of choosing a winner. Historical analysis and
roadmap documents live in `docs/analysis/` or `docs/roadmaps/`; durable plan
Markdown stays in `docs/plans/`. Plan tooling ignores non-plan Markdown beside
plans, and doctor emits a non-fatal warning if it remains there. Unresolved
plan-symbol warnings follow the same active-lifecycle default as stale
detection: draft, approved, executing, and blocked plans are current signals,
while historical plans remain on disk without blocking or warning by default.
A passed batch can be marked stale explicitly with `plan batch stale`; this
preserves the plan status and records a durable audit revision.

Revalidation is explicit rather than automatic. `plan batch reopen` accepts only
a stale batch in a done plan, requires a non-empty reason, and records a durable
`batch_reopened` revision. Reopening preserves stale evidence and old gate
results while changing the batch, its linked tasks, and the plan to `blocked`.
A subsequent `plan batch start` moves the reopened batch back into execution and
advances the batch-start revision, so completion can use only fresh gate
evidence recorded after that restart.

The same rule applies to open plans. `codeatlas update .` compares recorded
batch input fingerprints and, when `allow_update_plan_state` is true, marks only
`passed` batches in active plans stale through `plan_workflow.mark_batch_stale`.
The setting defaults to true and may be disabled in `codeatlas.config.json`.
When disabled, update is report-only and leaves plan Markdown unchanged. Stale
batches in open plans may be restarted with `plan batch start`; done plans still
require the explicit `plan batch reopen` transition.

## Context VM scopes and leases

Working-set pages carry optional `session_id`, `plan_id`, and `batch_id`
identities. Loading, status, budget accounting, prefetch, and eviction accept
the same three values. A non-empty field narrows the view, so `batch > plan >
session`; omitting all three selects the compatibility/global working set.
Rows from other scopes are never counted or evicted by a scoped operation.

Context writes hold a short-lived lease on the deterministic scope identity.
The lease is stored in `state.db` with an owner token and UTC expiry, is
released when the operation finishes, and expires so a crashed writer cannot
block a scope forever. A same-owner acquisition renews the lease; an expired
foreign lease can be taken over. CLI `context load/status/evict` and MCP
`context_load/context_status/context_evict` expose equivalent scope options.

## Plan context

`codeatlas plan context "<task>" --json` returns bounded, deterministic evidence
for planning. It combines indexed symbol matches, call-graph neighbours, and
project convention files. Each evidence item carries a stable ID, kind, ref,
reason, confidence, stale flag, and source path. The response includes suggested
context pages, an impact scope, engineering suggestions, and explicit
truncation reasons. No source bodies are dumped and no LLM is required.

The MCP tool `plan_context(query, root?)` returns the same JSON payload. If no
index exists, both surfaces return a bootstrap hint instead of pretending to
retrieve evidence.

JSON output uses sorted keys and stable field names. Errors are returned as
codes such as `PLAN_SCHEMA_INVALID`, `PLAN_NOT_FOUND`, `PLAN_DUPLICATE_ID`,
and `PLAN_FILE_NOT_FOUND`, rather than depending on localized prose.

## Contract boundary

Parsing, validation, template rendering, status grouping, and views live in
`codeatlas.plans`. Durable workflow mutations and snapshots live in
`codeatlas.plan_workflow`; derived memory lives in `codeatlas.plan_memory`, and
retrieval lives in `codeatlas.plan_context`. The CLI and MCP server only map
these functions to arguments, output, and exit codes.

The schema now covers durable plan history, execution evidence, staleness, and
deterministic plan context. It does not yet implement broad semantic retrieval,
file-dependency traversal, rollback, watchers, or concurrent locking. Later PRs
should extend these codes and views without changing their existing meanings.

The shipped template lives at [`docs/templates/plan-template.md`](templates/plan-template.md)
and is tested to lint clean.
