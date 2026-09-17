# Plan: CodeAtlas Upgrade Roadmap (v13)

Status: draft  
Version: 13  
Created: 2026-09-16  
Updated: 2026-09-16  
Supersedes: the phase roadmap sections in `docs/analysis/2026-09-16-codeatlas-current-state-and-plan-artifacts-roadmap.md`  
Purpose: turn the earlier analysis into an executable implementation order.

## Summary

This roadmap upgrades CodeAtlas from a code index into a **plan-aware project memory**. The first deliverable is not a bigger AI feature, but a stable contract between four layers:

| Layer | Source of truth | Purpose |
|---|---|---|
| Repo memory | `CODEATLAS.md`, `.codeatlas/detail/*.md` | Explain what the project is and where things live. |
| Task memory | `docs/plans/*.md` | Explain what is being built, why, and what remains. |
| Change memory | `.codeatlas/history/*.md` | Explain what changed, when, and with what evidence. |
| Engineering memory | Plan engineering profiles, conventions, and quality gates | Explain which architecture, quality, and safety rules apply to this change. |

The implementation order deliberately starts with a **stable plan artifact contract**, then adds retrieval, impact analysis, task-scoped context, and only later optional AI-heavy features.

## V3 optimization notes

V2 was directionally correct but still leaned too much toward a feature list. V3 adds the engineering constraints needed before implementation:

1. Separate the product core from tool adapters.
2. Make the plan file schema versioned and machine-checkable.
3. Give every phase explicit exit criteria and observability.
4. Treat semantic search and LLM enrichment as optional accelerators, not foundations.
5. Make rollback review-first and Git-native.
6. Add privacy, security, migration, and failure-mode constraints.

## V4 addition: batched execution control

The roadmap now treats "small, controlled implementation" as a first-class execution constraint. The default is not literally "always one file at a time", because some logically atomic changes legitimately touch an interface, implementation, and test together. Instead, every plan must define a reviewable **batch**:

1. One batch should usually map to one task or one cohesive code change.
2. A batch should touch as few files and symbols as possible.
3. Validation must run before the next batch starts.
4. High-risk changes should be split into smaller batches.
5. The agent must stop after each batch when the plan requires review.

This prevents large multi-file sweeps while avoiding artificial fragmentation of naturally coupled changes.

## V5 optimization notes

V4 defined batched execution, but did not yet make it safe for real multi-session use. V5 adds the missing operational contract:

1. Plans get stable revisions and conflict detection.
2. Batches get their own state machine, separate from task status.
3. The plan engine gets a small canonical command surface.
4. Evidence and impact results get explicit confidence and limits.
5. Rollback can target a batch instead of only a whole plan.
6. The implementation is gated on compatibility cases such as no-FTS, no-Git, Windows paths, and malformed plans.

## V6 optimization notes

V5 made the execution model safer, but still left several runtime details implicit. V6 closes those gaps:

1. Separate required and optional plan sections so simple plans stay lightweight.
2. Define where batch state lives and how validation runs are recorded.
3. Add a derived-index contract so CLI, MCP, and doctor read the same plan facts.
4. Complete the command surface for task updates, not just batch updates.
5. Make plan evidence carry the index version and capture time that produced it.
6. Add configuration, deterministic retrieval ordering, machine-readable errors, and non-blocking impact reporting.

## V7 addition: engineering-by-default

V6 made plan execution safer, but a plan could still describe only "what to build" without making the engineering expectations explicit. V7 adds an **engineering-by-default** layer:

1. Every non-trivial plan declares an engineering profile instead of relying on the agent to invent standards each time.
2. Profiles are tiered so small tasks remain lightweight and production-facing changes receive stronger gates.
3. Architecture decisions, quality gates, non-functional requirements, and plain-language explanations become part of the plan contract.
4. Batch validation checks the applicable engineering gates, not only whether code runs.
5. Non-engineers can see why each rule matters, while agents and CI receive machine-checkable commands and outcomes.

## V8 optimization: trust, approval, and readable execution

V7 defined the right engineering controls, but left three runtime questions implicit:

1. Who durably approved the plan, and which engineering profile/gate set did they approve?
2. Can a command gate be marked `passed` without actually running?
3. How can an agent or human read a large plan without loading every section?

V8 closes those gaps without adding a new product area:

1. Add a durable approval record and a frozen engineering manifest hash at approval time.
2. Distinguish auto-run command gates from explicitly reviewed gates; agents may report evidence, but cannot fabricate command-gate outcomes.
3. Run quality-gate commands with argv lists, timeouts, output limits, and no shell interpolation.
4. Add bounded plan views for summary, execution, engineering, and full rendering so plan files remain agent-friendly.
5. Treat post-approval semantic edits to scope, risk, architecture, or gates as reapproval-worthy changes.

## V9 optimization: implementation focus, reapproval, and derived diagrams

V8 defined the trust model, but the roadmap was still at risk of becoming too large to implement. V9 keeps the architecture while tightening the first deliverable:

1. Normalize the plan schema so writers and parsers do not disagree on fields such as `updated_at`.
2. Add a formal semantic revision and reapproval workflow instead of merely warning that an approved plan changed.
3. Render plan diagrams from structured task/batch data, so diagrams cannot contradict the plan.
4. Add a clear MVP scope fence: the first useful release is local plan creation, lint, approval, bounded rendering, batch execution, gate evidence, and update integration.
5. Defer dashboard, semantic search, watcher, rollback, MCP breadth, and LLM enrichment until the local core is stable.

## V10 optimization: evidence freshness and execution-state consistency

V9 exposed two state-machine problems that would break the trust model during real use:

1. A batch marked `passed` was called terminal, yet rollback could later invalidate that passed work.
2. A command gate could remain `passed` after the code, plan revision, or gate definition changed.

V10 fixes validation results as state-dependent evidence:

1. A passed batch can become `stale` when relevant inputs change.
2. A stale batch must be revalidated before it counts toward `done`.
3. Gate results record the plan revision, gate definition hash, and input-state fingerprint that produced them.
4. Rollback, semantic revision, and code update can mark affected validation as stale instead of pretending the old evidence still proves current behavior.
5. The command surface receives an implementation budget so the MVP does not absorb every future feature at once.

## V11 addition: adaptive testing strategy

Open-ended agents do not reliably schedule tests unless the plan says what must be tested and when. V6-V10 already required validation commands and quality gates, but that still allowed a plan to say only "run pytest" without requiring meaningful new coverage for the changed behavior.

V11 adds an adaptive **testing strategy** to the plan contract:

1. Non-trivial implementation tasks must state which tests will be added or updated before or alongside the implementation batch.
2. Bug fixes should add a failing reproduction test before the fix, or explicitly explain why that is impossible.
3. Tests are attached to batch validation, not deferred to a vague "test later" phase.
4. Required test depth follows the engineering profile, so prototypes stay lightweight while production changes receive stronger coverage.
5. Coverage percentages are not treated as success by themselves; the changed behavior must have executable assertions.

## V12 optimization: machine-checkable test contracts

V11 added testing strategy, but `new_tests` could still become an unverified narrative list. To keep testing requirements enforceable, the plan needs structured test references:

1. Each planned test has a stable ID, behavior under test, file path, kind, owning task/batch, and associated quality gate.
2. Lint verifies that planned test files exist after their owning task is done.
3. A test that is reused or omitted must state the reason; the gate, not the prose, decides whether it passed.
4. The derived plan index records test contracts so status, doctor, and CI can detect untested behavior without parsing natural language.
5. A `done` plan can be reopened explicitly when later work invalidates its required validation; stale evidence never remains hidden behind terminal status.

## V13 optimization: delivery decomposition and write authority

V12 was functionally coherent, but its "first implementation slice" had grown into ten workstreams in one PR. That contradicted the roadmap's own batched-execution rule. V13 does not add features; it makes the roadmap implementable:

1. Split the MVP into four independently reviewable PRs.
2. Define which component may mutate plan Markdown when code changes invalidate validation evidence.
3. Make the frontmatter `testing` block the machine-readable source of truth and the body section its explanation.
4. Freeze further roadmap expansion until Slice 1 produces implementation feedback.

## Architecture boundaries

| Boundary | Rule |
|---|---|
| Core | Plan parsing, validation, evidence indexing, impact analysis, and context scoping must be tool-agnostic. |
| CLI | CLI is the local command surface and should not become the only API. |
| MCP | MCP is the canonical agent-facing API for Codex, Cursor, Claude Code, and other clients. |
| Skill | `plan-artifacts` is a workflow adapter, not the source of truth. |
| Plan files | Markdown in `docs/plans/` is the human-readable source of truth. |
| Derived index | SQLite stores derived plan metadata for fast status, search, impact, and doctor checks. |
| Change memory | `.codeatlas/history/` remains the durable evidence for code evolution. |
| Engineering profiles | Profiles and quality gates are versioned project/user configuration, not prompt-embedded folklore. |
| Optional AI | LLM and embeddings must be behind interfaces and must never be required for the core index. |

## Core invariants

1. A plan must have a stable `id`, explicit `status`, and `schema_version`.
2. A plan must not silently claim evidence that CodeAtlas cannot resolve.
3. Code changes must be traceable to affected open plans when such plans exist.
4. Context pages must be scoped by task or plan when concurrency matters.
5. Rollback must be previewable and reversible-safe; it must never auto-destructively overwrite files.
6. Every core phase must be testable without an LLM or network dependency.
7. Non-trivial implementation must proceed in validated batches, not one large multi-file sweep.
8. Engineering requirements must be adaptive: a one-file prototype should not be forced through production ceremony, but security/data/API/public-contract work must not bypass relevant gates.
9. A plan's transition to `approved` must leave a durable approval record; conversational approval alone must not be the only audit trail.
10. A command quality gate must be executed by the plan engine or a trusted runner; an agent cannot mark it `passed` by assertion.
11. A validation result is valid only for the plan revision, gate definition, and input state that produced it.

## Plan identity, revisions, and concurrency

Markdown is the source of truth, but concurrent agents must not overwrite each other silently. Therefore, plan files need identity and revision metadata.

| Field | Purpose |
|---|---|
| `id` | Stable plan ID; never changes after creation. |
| `schema_version` | Contract version for parser behavior. |
| `revision` | Monotonic integer incremented on accepted plan edits. |
| `content_hash` | Hash of canonicalized plan content. |
| `updated_at` | Last accepted update time. |
| `last_writer` | Human, agent session, or tool that made the last accepted update. |
| `revision_type` | `semantic` or `state`; distinguishes approved-contract changes from execution bookkeeping. |
| `reapproval_required` | Whether an accepted semantic edit now blocks new batch execution. |
| `approval` | Durable approval metadata, including approver, time, basis, and engineering manifest hashes. |

Rules:

1. Plan-writing commands must read the current `revision` and reject stale writes.
2. If another writer changed the plan, the agent must re-read it before continuing.
3. Direct hand edits are allowed, but the next command should detect that `revision` or `content_hash` is stale and ask for confirmation.
4. The SQLite index stores a derived copy of the current plan state for fast queries, but the Markdown file remains authoritative.
5. Plan files outside the configured plans directory must not be indexed by default.
6. State updates such as batch status, task status, gate outcomes, and logs increment the revision but should not require reapproval unless they also change approved semantics.
7. Semantic edits after approval—especially goals, non-goals, files, symbols, risk, architecture decisions, or blocking gates—must be flagged as reapproval-worthy.

### Semantic revision and reapproval

Direct hand edits are allowed, but the canonical flow should be:

```bash
codeatlas plan revise <plan-id>      # apply or record a semantic edit
codeatlas plan diff <plan-id> --from-revision <n>
codeatlas plan approve <plan-id> --revision <n>
```

Rules:

1. `plan revise` classifies the accepted revision as `semantic` or `state`.
2. Adding, removing, or changing any of the following is semantic: goal, non-goals, task structure, dependencies, files, symbols, risk, batch structure, architecture decisions, security requirements, or blocking quality gates.
3. Updating a task status, batch status, gate outcome, execution log, evidence capture time, or `last_writer` is normally a state change.
4. A semantic revision to an approved or executing plan sets `reapproval_required: true`.
5. While `reapproval_required` is true, the plan must not start a new batch. An already-active batch may finish validation, but must not continue beyond a natural stopping point.
6. `plan approve --revision <n>` clears the flag, records the new approval, and refreshes the engineering manifest hashes.
7. If a hand edit changes semantic content without updating `revision_type`, `plan lint` marks it `reapproval_required` based on the canonical diff classifier.
8. `plan diff` must distinguish semantic changes, state changes, and formatting-only changes.
9. A semantic revision marks existing command-gate outcomes `stale` because their fingerprints no longer match the approved plan revision.
10. Later code changes may mark a `done` plan's required validation stale, but `update` must not silently rewrite the plan status. `doctor` reports the conflict, and reopening `done` to `blocked` or `executing` requires an explicit transition.

## Non-goals

- Do not replace Git.
- Do not make CodeAtlas an agent runtime.
- Do not require an LLM for indexing, planning, impact analysis, or doctor checks.
- Do not build a plugin marketplace before the local workflow is stable.
- Do not aim for a perfect call graph; preserve confidence and approximate labels.

## Guiding rules

1. Markdown is the human-readable source of truth for plans; SQLite is the derived index and query surface.
2. Rule-based behavior must remain the default; LLM/enrichment features must be optional.
3. Every plan should cite CodeAtlas evidence instead of relying on agent guesses.
4. Every code-changing phase must end with `codeatlas update .` and `codeatlas doctor`.
5. Do not build rollback, embedding, or watcher features before the plan contract is stable.
6. Prefer many small, validated changes over one large, hard-to-review change.
7. Engineering quality should be built into plans by default, not added after the code has already drifted.

## Batched execution policy

### Goal

Prevent the agent from making one large, difficult-to-review change. A plan should be executed as a sequence of small, validated batches.

### Default rule

| Change type | Recommended batch size |
|---|---|
| High-risk API, schema, security, migration, or public contract change | 1 file or 1 symbol per batch |
| Medium-risk service, workflow, CLI, or refactor change | 1 cohesive task, usually 1-3 files |
| Low-risk UI copy, comment, docs, formatting, or mechanical rename | Up to 5 files, if mechanical and easy to verify |
| Mixed multi-layer change | Split into interface, implementation, test, and docs batches |

### Execution contract

1. Before changing a file, the agent must name the active batch.
2. A batch may proceed only when its predecessor is validated or explicitly deferred.
3. After each batch, the agent must:
   - update the task status in the plan
   - record what changed in `Execution log`
   - run the batch-level validation
   - record the outcome of each applicable engineering gate
   - stop if the plan requires human review
4. The agent must not start a new batch after a failed validation unless the plan explicitly says the failure is expected.
5. A batch should not silently expand into unrelated files or symbols.

### Anti-patterns

The agent must avoid:

1. "Refactored the whole project" without intermediate checkpoints.
2. Editing many files before running any validation.
3. Mixing unrelated fixes in one batch.
4. Updating many files while leaving the plan status unchanged.
5. Treating "one file at a time" as more important than semantic completeness.

### Plan-level representation

The plan frontmatter may optionally declare execution limits:

```yaml
change_control:
  mode: strict | adaptive
  max_files_per_batch: 1-5
  max_symbols_per_batch: 1-8
  require_validation_after_batch: true
```

Defaults:

- `mode: adaptive`
- `max_files_per_batch`: derived from task risk
- `max_symbols_per_batch`: derived from task risk
- `require_validation_after_batch: true`

`strict` mode is appropriate for schema changes, migrations, security work, and public API changes.

`adaptive` mode is appropriate for most normal implementation work, because it lets one cohesive task touch a small set of related files without pretending that each file is an independent change.

### Batch state machine

Batch status is separate from task status because a batch may be in validation even when its task is still considered in progress.

| Batch status | Meaning | Allowed transitions |
|---|---|---|
| `pending` | Defined but not started. | `in-progress`, `blocked`, `skipped` |
| `in-progress` | Code changes are being made. | `validating`, `blocked`, `failed` |
| `validating` | Batch-level validation is running. | `passed`, `failed`, `blocked` |
| `passed` | Validation succeeded for the recorded input state. | `stale` |
| `failed` | Validation failed. | `in-progress`, `blocked`, `skipped` |
| `blocked` | A dependency, review, or external condition stopped the batch. | `in-progress`, `pending`, `skipped` |
| `skipped` | Explicitly deferred or no longer required. | terminal for the batch |
| `stale` | A previously passed batch's inputs changed; its old validation no longer proves current behavior. | `validating`, `failed`, `blocked` |

Rules:

1. A batch must record its last validation result.
2. A batch cannot be marked `passed` without a recorded validation result.
3. A failed batch must record the failing command and short diagnostic.
4. A skipped batch must record why it was skipped.
5. Batch IDs are stable and must not be reused after cancellation.
6. `passed` is terminal only while its recorded input-state fingerprint remains valid.
7. If a relevant file, symbol, plan revision, gate definition, or workspace input changes, a blocking command gate and its batch become `stale`.
8. A `stale` batch cannot count as completed until it re-enters `validating` and all blocking gates pass again.

### Plan status derivation

Plan status remains explicit, but lint can check whether it is consistent with tasks and batches:

| Plan status | Consistency rule |
|---|---|
| `draft` | Must not contain `passed`, `failed`, or `stale` batches. |
| `approved` | Should have no `in-progress`, `validating`, or `stale` batches. |
| `executing` | Must have at least one active or completed batch. |
| `blocked` | Should have at least one `blocked` batch or task. |
| `done` | All required tasks are `done`; all required batches are `passed` or `skipped`; required test contracts are implemented or explicitly reused; no required batch, blocking gate, or test gate is `stale`. |
| `cancelled` | Remaining work is cancelled; already-completed batches remain as history. |

## Engineering-by-default policy

### Goal

Make good engineering defaults part of the plan itself, so an agent does not merely generate "working code". The plan should encode the architecture boundary, standards, tests, safety rules, and explanations needed for a maintainable project.

The policy is deliberately **tiered**, not bureaucratic: it should make lightweight tasks easier to do correctly, while making high-risk work harder to do casually.

### Engineering profiles

| Profile | Intended use | Required emphasis | Explicitly avoided |
|---|---|---|---|
| `prototype` | Disposable demos, scratch scripts, design experiments | Minimal modules, quick validation, clear cleanup or promotion path | Heavy documentation, full CI ceremony, premature abstractions |
| `product` | Normal non-trivial implementation | Cohesive module boundaries, tests, error handling, docs, maintainability | Enterprise process for small changes |
| `production` | Security, auth, payments, data, migration, public API, reliability-critical work | Strong contracts, compatibility, observability, rollback, threat modeling, review gates | Ambiguous ownership, silent breaking changes, unvalidated migrations |

Default selection should be adaptive:

1. A small demo or throwaway experiment defaults to `prototype`.
2. Most non-trivial feature, bug-fix, CLI, service, or refactor work defaults to `product`.
3. A change touching auth, secrets, personal data, schema migration, public API, deployment, or failure-sensitive infrastructure defaults to `production`.
4. The agent may upgrade a profile when evidence reveals hidden risk, but must not silently downgrade `production` to `product`.
5. A downgrade from the configured default must be visible in the plan and accepted during approval.

### Plan frontmatter

Add an optional-but-recommended engineering block:

```yaml
engineering:
  profile: prototype | product | production
  architecture_style: none | layered | modular-monolith | event-driven | plugin
  standards: []
  quality_gates: []
  plain_language: true
  profile_revision: optional-version
approval:
  decision: approved | changes-requested | rejected
  approved_by: user-or-role
  approved_at: YYYY-MM-DDTHH:MM:SSZ
  basis: conversation | review-doc | issue | ci-review
  profile_hash: resolved-profile-hash
  gate_set_hash: resolved-gate-set-hash
```

Rules:

1. If the field is omitted, `plan lint` applies the configured default and emits a warning.
2. `standards` and `quality_gates` may be named references to reusable configuration, so plans do not copy large rule bodies.
3. `plain_language: true` means every named gate or non-obvious engineering term must have a short user-facing explanation.
4. Profiles are versioned with the project/user configuration; the plan records the profile name and relevant gates, not a hidden mutable rulebook.
5. `approval` is omitted while the plan is `draft`. It is required before `status: approved` becomes valid.
6. The approval block captures the resolved engineering contract hashes at approval time; later configuration drift is warned by `doctor`.

### Adaptive body sections

| Section | Requirement | Purpose |
|---|---|---|
| `Engineering requirements` | required for `product` and `production`; recommended warning for `prototype` | State the maintainability, correctness, and safety expectations. |
| `Architecture decisions` | required when crossing a boundary, adding a module, changing a public contract, or choosing a non-obvious pattern | Explain the chosen shape and rejected alternatives briefly. |
| `Testing strategy` | required for `product` and `production`; recommended for `prototype` | State which new or updated tests prove the changed behavior. |
| `Quality gates` | required for `product` and `production`; recommended for `prototype` | List the commands or checks that prove quality. |
| `Non-functional requirements` | conditional for performance, reliability, resource, accessibility, or concurrency concerns | Prevent "works once on my machine". |
| `Security and privacy` | conditional and required when the change touches auth, secrets, user data, inputs, files, network, or deployment | Make risk visible before implementation. |
| `Compatibility and migration` | conditional for schema, config, public API, persisted data, or protocol changes | Prevent silent breakage. |
| `Observability` | conditional for service, workflow, CLI, or reliability-critical behavior | Make failures diagnosable. |
| `Documentation` | required for user-facing, public-contract, configuration, or architectural changes | Keep the project learnable. |
| `Accessibility` | conditional for UI or generated documents | Ensure usable output, not only visually polished output. |
| `Decision records` | optional; recommended for important architecture or tradeoff choices | Preserve why a decision was made. |

Empty conditional sections may be omitted only when the plan explains why they do not apply. For example, a prototype may omit `Observability`, but a production migration must not omit `Compatibility and migration`.

### Adaptive testing strategy

Validation commands prove that tests ran; they do not prove that the right tests exist. Each plan should therefore include a short `Testing strategy`.

```yaml
testing:
  approach: test-with-change | reproduction-first | test-after-with-reason
  tests:
    - test_id: T-001
      kind: unit | integration | contract | migration | regression | smoke
      behavior: <behavior that must be proven>
      files:
        - tests/test_refresh.py::test_refresh_preserves_session
      gate_id: unit-tests
      batch: B1
      task: 1
      disposition: implement | reuse | omit
      reason: required when disposition is reuse or omit
  regression_targets: []
  manual_checks:
    - check_id: M-001
      behavior: <visible result to verify>
      artifact: docs/plans/artifacts/<plan-id>/manual-check.md
```

Rules:

1. A `product` or `production` plan must identify the changed behavior and the tests that prove it.
2. The frontmatter `testing` block is the machine-readable contract source of truth; the `Testing strategy` body section explains intent and may add narrative context.
3. Lint rejects conflicts between the frontmatter test IDs/files/gates and the body section's named tests.
4. Every `implement` test must reference one or more existing or planned test files and one applicable quality gate.
5. A `reuse` test must name the existing test and explain why it already proves the behavior.
6. An `omit` test must be marked `required: false` or replaced with an explicit reason; vague omission is invalid.
7. Manual checks must point to a reviewable artifact and should not be used for production blocking behavior when an executable test is practical.
8. A prototype may use one smoke test, script, or recorded manual check, but must state how the result was verified.
9. For bug fixes, use `reproduction-first` when practical: add a failing test, then make it pass.
10. For public APIs, file parsing, persistence, queue/event flows, or service boundaries, add integration or contract tests when a unit test cannot prove the boundary.
11. For schema or config migrations, test both the fresh path and migration of representative existing data.
12. For error paths, test invalid input, permission failure, timeout, network/storage failure, or retry behavior when such failure is part of the task.
13. For UI or CLI changes, test the visible behavior or add an executable smoke/manual checklist.
14. Do not require a global coverage number by default. If a project uses coverage, report it as informational and lint only the changed behavior.
15. If no new tests are added, `Testing strategy` must say why. Acceptable reasons include docs-only changes, generated output, throwaway prototype, or existing tests already covering the behavior.
16. Tests belong in the same batch as the implementation when they prove that batch. A separate test-only batch is allowed only for naturally separable integration, performance, migration, or end-to-end validation.
17. A test contract is complete only when the owning task is done, referenced test files exist, and the associated gate has a current passing outcome.

Recommended test depth:

| Profile | Minimum testing expectation |
|---|---|
| `prototype` | One smoke check, demo assertion, or recorded manual verification. |
| `product` | Unit or integration tests for changed behavior and relevant regressions. |
| `production` | Unit, integration/contract, regression, migration or compatibility, security review, and failure-path tests as applicable. |

### Quality gates

A quality gate is not merely a sentence such as "write good tests". It must be executable or explicitly classified as a review gate.

```yaml
quality_gates:
  - gate_id: unit-tests
    kind: command
    command: ["pytest", "-q"]
    cwd: repo-root
    timeout_seconds: 120
    output_limit: 4000
    blocking: true
    description: Proves that the changed behavior has automated coverage.
  - gate_id: regression-tests
    kind: command
    command: ["pytest", "-q", "tests/regression"]
    cwd: repo-root
    timeout_seconds: 180
    output_limit: 4000
    blocking: true
    description: Ensures previously working behavior still works.
  - gate_id: integration-tests
    kind: command
    command: ["pytest", "-q", "tests/integration"]
    cwd: repo-root
    timeout_seconds: 300
    output_limit: 4000
    blocking: true
    description: Proves that modules and external boundaries work together.
  - gate_id: type-check
    kind: command
    command: mypy
    blocking: false
    description: Catches type-level regressions before they reach production.
  - gate_id: migration-review
    kind: review
    blocking: true
    description: Confirms that data can be migrated and safely rolled back.
```

Rules:

1. `kind: command` gates must be runnable locally and offline unless the user explicitly configures an external tool.
2. `kind: review` gates require a human or explicit agent-reported review artifact; they must not be auto-marked as passed merely because tests passed.
3. A blocking gate that cannot run must fail with a clear reason instead of being skipped silently.
4. Recommended gates may be deferred with a recorded reason, but their deferral remains visible in `plan status`.
5. Gate outcomes belong in the batch execution log, not in free-form chat memory.
6. Command gates use argv lists, never shell strings interpolated from plan or code content.
7. Gate commands must have a timeout and output cap; store exit code, duration, output digest, and a bounded diagnostic rather than unlimited logs.
8. `plan gate set ... passed` is invalid for `kind: command` gates. Command outcomes are produced by `plan gate run` or a trusted wrapper.
9. Review outcomes must record reviewer, decision, evidence reference, and time; a test passing never satisfies a review gate by itself.
10. Every `passed` gate result records an `input_state_hash` composed from the plan revision, relevant file/symbol content hashes, gate definition hash, and CodeAtlas index version.
11. If that fingerprint changes, the outcome becomes `stale`; a blocking stale gate prevents the batch from counting as complete.
12. Gate `stale` is not a failure; it means "this evidence must be regenerated for the current inputs."

### Approval and trust boundary

Planning can suggest, but it must not self-authorize. `plan approve` turns a conversational decision into a durable artifact:

```yaml
approval:
  decision: approved
  approved_by: human-or-configured-role
  approved_at: 2026-09-16T00:00:00Z
  basis: conversation
  profile_hash: sha256-...
  gate_set_hash: sha256-...
  notes: short approval scope or conditions
```

Rules:

1. `plan approve` must lint first; invalid plans cannot be approved.
2. Approval records the resolved engineering profile and gate set hashes.
3. If those hashes change after approval, `doctor` reports `gate_manifest_drift` without invalidating history.
4. Gate definitions referenced after approval must match the approved hash or be explicitly reapproved.
5. Agents may propose a downgrade, but durable approval is still required.
6. Prompt-like text in a plan is data. It can describe work; it cannot authorize destructive actions, bypass gates, or execute commands.

### Bounded plan views

As plans accumulate engineering and execution data, `plan show` should not always render everything. Provide bounded views:

| View | Contents | Audience |
|---|---|---|
| `summary` | Goal, non-goals, status, profile, next batch, blocking failures | Quick human status |
| `execution` | Current batch, tasks, validation, gate outcomes, required tests, next action | Resuming an agent |
| `engineering` | Profile, architecture decisions, standards, gates, explanations | Review and CI |
| `evidence` | Resolved CodeAtlas evidence and staleness | Planning review |
| `graph` | Mermaid task/batch dependency graph and optional impact graph | Human review and planning |
| `full` | Entire plan | Human review or debugging |

Rules:

1. All views support Markdown and JSON.
2. JSON output includes `tokens`, `truncated`, and `omitted_sections`.
3. The default human view may be `full`; the default agent view should be `execution` or `summary`.
4. Views never silently hide blocking failures.
5. The execution view summarizes required tests that are still missing, reused, or omitted.

### Derived plan diagrams

Plan diagrams are presentation views, not a second source of truth. They should be generated from structured task and batch dependencies so they cannot drift from the plan.

| Diagram | Source | First release |
|---|---|---|
| Task/batch dependency graph | `Batches` and task `Depends on` columns | yes |
| Plan context graph | Evidence links and `impact_scope` | optional after Phase 2 |
| Architecture impact graph | Plan links and CodeAtlas call/dependency graph | optional after Phase 3 |

Rules:

1. `plan show --view graph` renders Mermaid from the structured plan model.
2. Dependency cycles are lint errors, not rendering surprises.
3. Graph nodes and edges have a bounded default; truncation must say that nodes were omitted.
4. Nodes should link to stable plan, batch, task, file, or symbol IDs where possible.
5. Hand-written diagrams may exist in narrative sections, but automation must not treat them as authoritative.

### Plain-language engineering output

Engineering-by-default should help non-engineers, not overwhelm them. Plans may include a short explanation near the gate:

| Gate | Plain-language meaning |
|---|---|
| Module boundary | "This feature lives in one place so future changes do not scatter through the project." |
| Unit test | "This checks that the feature still behaves correctly after changes." |
| Regression test | "This keeps a bug that was fixed before from coming back." |
| Integration test | "This checks whether several parts work together, not only each part alone." |
| Type check | "This catches mistakes where data has the wrong shape." |
| Security review | "This checks whether an attacker could misuse the new input or connection." |
| Migration review | "This checks whether existing data can survive the change." |
| Observability | "This adds a signal so failures can be found without guessing." |

The agent should use plain language in the plan body and explanation output, while preserving exact commands and identifiers in frontmatter or tables for automation. Explanations should honor `plain_language_locale`; a Chinese-speaking user should not need to decode English engineering jargon to understand a blocking gate.

### Integration with batch execution

Every batch inherits the plan's applicable engineering gates.

1. `plan batch set ... --status validating` must report which gates apply.
2. A batch cannot move from `validating` to `passed` while any applicable blocking gate is `failed` or `not-run`.
3. A batch may move to `passed` with recommended gates deferred only when the plan explicitly allows deferral and records the reason.
4. Engineering failures are not always code failures; for example, missing migration review or missing documentation can block a `production` batch.
5. `doctor` warns when a plan claims an engineering profile but has no applicable quality gates.
6. `doctor` warns when a `production` plan references an API, migration, or security task without the corresponding gates.

### Reusable standards

To avoid repeating project conventions in every plan, support project-level engineering profiles:

```text
.codeatlas/engineering/profiles/*.yaml
.codeatlas/engineering/gates/*.yaml
```

Rules:

1. Profiles define defaults by change type, language, and risk.
2. Gates define commands, expected files, review requirements, and blocking behavior.
3. Built-in fallback profiles work even when no custom file exists.
4. Custom profiles are additive and versioned; they must not execute embedded shell content during parsing.
5. The same profile names should be usable by Skill, CLI, MCP, and CI.

This makes the feature useful across agents: Codex, Cursor, Claude Code, or CI can consume the same engineering contract instead of relying on one prompt.

## Canonical plan command surface

The plan engine should expose one small command surface that both CLI and MCP can reuse. Skill-specific prompts should call these commands instead of inventing another format.

| Command | Purpose |
|---|---|
| `plan new <slug>` | Create a plan from the current template. |
| `plan show <plan-id> [--view summary|execution|engineering|evidence|graph|full]` | Render one bounded plan view as Markdown, Mermaid, or JSON. |
| `plan status` | List plan, task, and batch status. |
| `plan lint` | Validate schema, references, batches, and transitions. |
| `plan transition <plan-id> <status>` | Apply a plan status transition with conflict detection. |
| `plan approve <plan-id>` | Lint and durably record approval with engineering manifest hashes. |
| `plan revise <plan-id>` | Apply/record an accepted semantic or state revision. |
| `plan diff <plan-id> --from-revision <n>` | Show semantic, state, and formatting-only changes. |
| `plan task set <plan-id> <task-id> <status>` | Update one task status with conflict detection. |
| `plan batch set <plan-id> <batch-id> <status>` | Update batch state and validation evidence. |
| `plan gate run <plan-id> <batch-id> <gate-id>` | Execute a command gate with timeout and output limits. |
| `plan gate review <plan-id> <batch-id> <gate-id>` | Record reviewer and evidence for a review gate. |
| `plan gate set <plan-id> <batch-id> <gate-id> <outcome>` | Record `failed`, `deferred`, or `not-run`; `passed` requires `gate run` or `gate review`. |
| `plan context "<task>"` | Retrieve evidence for planning. |
| `plan impact <plan-id>` | Compute direct, indirect, and possible impact. |

Rules:

1. Every mutating command must support `--json`.
2. Every mutating command must reject a stale `revision`.
3. Every command must work without network access.
4. Commands should avoid printing source bodies unless explicitly requested.
5. MCP tools should mirror these commands rather than define different semantics.
6. Every command should emit stable error codes such as `PLAN_NOT_FOUND`, `PLAN_SCHEMA_INVALID`, `PLAN_REVISION_CONFLICT`, `INVALID_TRANSITION`, `BATCH_STATE_INVALID`, `GATE_NOT_FOUND`, `GATE_KIND_INVALID`, `GATE_TIMEOUT`, `GATE_MANIFEST_DRIFT`, `REAPPROVAL_REQUIRED`, and `TEST_CONTRACT_MISMATCH`.
7. Read commands should also support `--json`; JSON is the preferred interface for agents.
8. Command-gate execution is enabled only by explicit local configuration; the engine must never execute arbitrary commands extracted from plan text.
9. `plan approve` must reject a plan whose current revision differs from the revision being approved unless the difference is only state bookkeeping.
10. `plan gate set` may never set a command gate to `passed` or a review gate to `passed`; use the command-specific evidence-producing subcommands.

### Command-surface budget

The MVP command surface is already near its useful limit. To prevent every later idea from becoming a new subcommand:

1. MVP core: `new`, `show`, `status`, `lint`, `transition`, `approve`, `revise`, `diff`, `task set`, `batch set`, `gate run`, `gate review`, and narrowly scoped `gate set`.
2. Later after retrieval: `plan context`.
3. Later after impact indexing: `plan impact`.
4. Later after rollback: `plan rollback`.
5. New commands must either replace overlapping commands or prove that existing commands cannot express the workflow.
6. Agent-facing MCP should expose workflows as tools, not mirror every internal flag.

## Configuration contract

Plan behavior should be configurable without hard-coding this repository's conventions into the engine.

| Setting | Default | Purpose |
|---|---|---|
| `plans_dir` | `docs/plans` | Location of Markdown plan files. |
| `plan_schema_version` | `1` | Current accepted schema version. |
| `default_batch_mode` | `adaptive` | New-plan default batch control. |
| `max_files_per_batch` | task-risk derived | Upper bound used by lint. |
| `max_symbols_per_batch` | task-risk derived | Upper bound used by lint. |
| `default_engineering_profile` | adaptive (`prototype` / `product` / `production`) | Default profile for new plans. |
| `engineering_profiles_dir` | `.codeatlas/engineering/profiles` | Reusable engineering profile files. |
| `quality_gates_path` | `.codeatlas/engineering/gates` | Reusable local quality-gate definitions. |
| `blocking_quality_gates` | profile-defined | Gates that prevent a batch from passing. |
| `plain_language_mode` | `adaptive` | Whether plans explain engineering terms for non-engineers. |
| `quality_gate_timeout_seconds` | bounded default | Maximum runtime for one command gate. |
| `quality_gate_output_limit` | bounded default | Maximum characters/tokens retained from gate output. |
| `allow_quality_gate_execution` | `true` only for built-ins; otherwise explicit | Controls whether the plan engine executes command gates. |
| `allow_update_plan_state` | `true` | Whether `codeatlas update .` may write state-only stale transitions to plan Markdown. |
| `require_durable_approval` | `true` | Require a recorded approval before execution. |
| `default_plan_view` | `execution` for agents, `full` for humans | Prevents unbounded rendering. |
| `plan_view_token_limit` | bounded default | Maximum size of one rendered plan view. |
| `plan_graph_max_nodes` | bounded default | Maximum nodes rendered in a dependency or impact graph. |
| `plain_language_locale` | user/project locale | Language used for non-engineer explanations. |
| `retrieval_max_results` | bounded default | Maximum `plan context` evidence items. |
| `retrieval_max_tokens` | reuse context budget | Output size cap. |
| `impact_graph_depth` | bounded default | Maximum dependency/caller traversal depth. |
| `strict_required_risks` | `high` | Risk levels that must use strict batch control. |

Rules:

1. Settings may live in project configuration, user configuration, or CLI flags; CLI flags win.
2. Unknown plan-related settings should produce warnings in `doctor`.
3. Unknown engineering profiles or gate names should produce actionable warnings, not fail indexing.
4. Built-in fallback profiles and gates must work without custom files.
5. Defaults must be safe, offline, and local-first.
6. Quality-gate commands must be declared in trusted configuration, not discovered from Markdown at runtime.
7. If durable approval is disabled, `doctor` must report that the setup loses its approval audit trail.
8. If `allow_update_plan_state` is false, staleness is report-only and `doctor` explains that Markdown plan state may lag behind code.

## Derived plan index contract

The Markdown plan file is authoritative; SQLite is a rebuildable projection. The projection should make status, search, impact, and doctor checks cheap.

| Table | Purpose |
|---|---|
| `plan_files_meta` | One row per plan file: ID, path, schema version, revision, hash, status, updated time. |
| `plan_revisions` | Revision number, semantic/state classification, content hash, writer, and reapproval requirement. |
| `plan_batches` | Batch ID, title, dependency IDs, state, last validation result. |
| `plan_tasks` | Task ID, batch ID, dependencies, risk, files, symbols, status, validation. |
| `plan_tests` | Structured test contracts: behavior, kind, file, owning task/batch, associated gate, disposition, and reason. |
| `plan_evidence` | Evidence ID, kind, reference, capture time, index version, confidence, stale state. |
| `plan_links` | Normalized plan-to-file and plan-to-symbol links for impact analysis. |
| `plan_logs` | Execution events used for resume and audit. |
| `plan_engineering_profiles` | Engineering profile selected by each plan. |
| `plan_quality_gates` | Gates associated with plans or batches, including `passed`, `failed`, `deferred`, `not-run`, and `stale` outcomes plus input fingerprints. |
| `plan_architecture_decisions` | Important architecture decisions and affected boundaries. |
| `plan_approvals` | Durable approval decisions, approvers, basis, and engineering manifest hashes. |

Rules:

1. `plan update` or a dedicated `plan index` command may refresh this projection.
2. If the projection is deleted, it must be reconstructable from Markdown.
3. If the Markdown file and projection disagree, `doctor` reports the conflict and rebuilds only after confirmation.
4. The projection must not contain executable content from plan Markdown.
5. Engineering profiles and gate definitions remain configuration inputs; the projection records the names, versions, and outcomes needed for audit.
6. Gate outcome records include command hash, exit code, duration, output digest, runner version, and the approved manifest hash when available.
7. Approval records are append-friendly; changing an approved semantic contract creates a new reapproval decision rather than erasing the old one.

### Staleness write authority

When `codeatlas update .` detects that a relevant file or symbol changed:

1. Compute the new impact and compare the relevant gate `input_state_hash` values.
2. Treat stale results as state-only plan updates, not semantic revisions.
3. Mutate plan Markdown only through the canonical plan writer, with revision increment, `last_writer`, timestamp, and an execution-log event.
4. Skip and report malformed or revision-conflicted plans; never overwrite them during indexing.
5. Record both the Markdown state and derived projection in one logical operation; if the Markdown write fails, do not persist the projection as authoritative.
6. Do not change approved goals, scope, architecture, or gate definitions during `update`; stale marking may not bypass reapproval.

Default behavior should be conservative: if plan state writing is disabled or the plan file is locked, `update` reports required revalidation in JSON and leaves the Markdown unchanged.

## Implementation order

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Plan artifact contract and baseline checks | none |
| 1 | Minimal plan engine + `plan-artifacts` Skill | 0 |
| 2 | `plan context` retrieval | 0, 1 |
| 3 | Plan-aware `update` impact reporting | 0, 1 |
| 4 | Task/session-scoped context VM | 0, 1 |
| 5 | Optional description enrichment | 1 |
| 6 | Semantic search / embeddings | 2 |
| 7 | Git-aware rollback | 3 |
| 8 | Watcher, CI, language expansion | 3 |

## Execution slices

The roadmap should be delivered in reviewable slices rather than one large migration:

| Slice | Contents | Why |
|---|---|---|
| Slice 1 | Phase 0 + minimal Phase 1 | Establishes the plan contract and smallest useful workflow. |
| Slice 2 | Phase 2 retrieval | Makes plans evidence-backed instead of guess-backed. |
| Slice 3 | Phase 3 impact reporting | Connects code changes to task memory. |
| Slice 4 | Phase 4 context scoping | Makes multi-terminal and multi-plan use safe. |
| Slice 5 | Phase 5-7, as needed | Adds enrichment, semantic search, and rollback only after the core is stable. |

## MVP scope fence

The full roadmap is deliberately larger than the first product. To prevent planning infrastructure from becoming its own project, the first useful release should implement only the following:

| Must have in MVP | Why |
|---|---|
| Create, parse, lint, and show local plan files | Establishes the artifact contract. |
| Stable revisions, conflict detection, and bounded views | Makes multi-step and multi-agent work safe. |
| Durable approval and semantic reapproval | Prevents agents from self-authorizing scope changes. |
| Adaptive engineering profile and gate references | Encodes quality without heavyweight ceremony. |
| Machine-checkable testing strategy for changed behavior | Prevents "implementation only, tests later" workflows. |
| Batch/task status transitions and execution logs | Allows interrupted work to resume. |
| Minimal command-gate runner and review-gate evidence | Makes validation trustworthy. |
| Gate input fingerprints and stale-result detection | Prevents old test evidence from proving changed code. |
| One derived task/batch dependency graph | Gives users a diagram without a dashboard. |
| `codeatlas update .` integration and doctor checks | Connects task memory to code memory. |

The MVP should explicitly defer:

- semantic search and embeddings;
- optional LLM enrichment;
- file watcher daemon;
- Git-aware rollback;
- full CI dashboards and PR bots;
- broad MCP parity;
- multi-language expansion;
- complex UI beyond CLI/Mermaid output.

These can be added only after the MVP passes its exit criteria and has at least one real end-to-end implementation workflow.

## Phase 0: Plan artifact contract and baseline checks

### Goal

Define what a plan file is before implementing automation around it.

### Tasks

1. Define the Markdown plan contract:

   ```yaml
   ---
   schema_version: 1
   id: 2026-09-16-<short-slug>
   title: <task title>
   status: draft | approved | executing | blocked | done | cancelled
   created: YYYY-MM-DDTHH:MM:SSZ
   updated_at: YYYY-MM-DDTHH:MM:SSZ
   revision: 1
   content_hash: <canonical-plan-hash>
   revision_type: semantic | state
   reapproval_required: false
   owner: human | agent
   last_writer: human | agent-session | tool-name
   files: []
   symbols: []
   context_pages: []
   evidence: []
   change_control:
     mode: adaptive
   engineering:
     profile: product
     architecture_style: none
     standards: []
     quality_gates: []
     plain_language: true
   testing:
     approach: test-with-change
     tests: []
     manual_checks: []
   approval: null
   ---
   ```

2. Define body sections:

   | Section | Requirement | Purpose |
   |---|---|---|
   | `Goal` | required | State the delivered outcome. |
   | `Non-goals` | required | Prevent scope creep. |
   | `Tasks` | required | Provide the execution source of truth. |
   | `Validation` | required | Define how completion is proven. |
   | `Testing strategy` | adaptive | Define new/updated tests, regression targets, and why omitted tests are acceptable. |
   | `Execution notes` | required | State execution rules and limits. |
   | `Engineering requirements` | adaptive | State architecture, standards, and quality expectations for this change. |
   | `Architecture decisions` | conditional | Explain important boundaries, contracts, or tradeoffs. |
   | `Quality gates` | adaptive | List executable and review-based checks. |
   | `Security and privacy` | conditional | Required for auth, secrets, user data, inputs, network, or deployment work. |
   | `Compatibility and migration` | conditional | Required for schema, config, persisted data, protocol, or public API work. |
   | `Documentation` | adaptive | Required for user-facing, public-contract, config, or architectural changes. |
   | `Current understanding` | optional | Capture current versus target behavior. |
   | `Assumptions` | optional | List assumptions that need review. |
   | `CodeAtlas evidence` | optional | Record resolved evidence for the plan. |
   | `Batches` | optional | Record batch state when a plan has more than one batch. |
   | `Execution log` | optional until execution starts | Record what happened during implementation. |

   Empty optional sections may be omitted. Once execution starts, `Execution log` becomes required.

3. Define evidence item shape:

   ```yaml
   evidence:
     - evidence_id: ev-001
       kind: overview | module_detail | symbol | history | context_page
       ref: <path or qualified symbol>
       reason: <why this evidence matters>
       captured_at: YYYY-MM-DDTHH:MM:SSZ
       index_version: 42
       query_hash: optional-for-retrieval-evidence
   ```

4. Add a lightweight parser for plan frontmatter.

5. Define the task table schema:

   ```markdown
   | # | Batch | Task | Depends on | Risk | Files | Symbols | Validation | Status |
   |---|---|---|---|---|---|---|---|---|
   | 1 | B1 | Add refresh service | none | medium | `auth/refresh.ts` | `AuthService.refresh` | unit-tests gate + new `AuthService.refresh` cases | pending |
   ```

   Allowed task risk values:

   - `low`
   - `medium`
   - `high`

   Allowed task status values:

   - `pending`
   - `in-progress`
   - `blocked`
   - `done`
   - `skipped`

6. Define the optional batch table schema:

   ```markdown
   | Batch | Purpose | Depends on | Status | Last validation |
   |---|---|---|---|---|
   | B1 | Add service boundary | none | pending | none |
   | B2 | Wire API client | B1 | pending | none |
   ```

   This table is optional for single-batch plans. For multi-batch plans, it is required.

7. Define execution log records:

   ```yaml
   - at: YYYY-MM-DDTHH:MM:SSZ
   batch: B1
   task: 1
   event: code-change | test-change | validation-pass | validation-fail | quality-gate | blocked | resumed
     files: []
     symbols: []
     command: optional validation or update command
     exit_code: optional integer
     gate: optional quality-gate ID
   gate_outcome: passed | failed | deferred | not-run | stale
   gate_definition_hash: optional-for-command-gates
   input_state_hash: optional-for-command-gates
     note: short human-readable result
   ```

8. Define plan status transition rules:

   | From | Allowed transitions |
   |---|---|
   | `draft` | `approved`, `cancelled` |
   | `approved` | `executing`, `draft`, `cancelled` |
   | `executing` | `blocked`, `done`, `cancelled` |
   | `blocked` | `executing`, `done`, `cancelled` |
   | `done` | `executing`, `blocked` (explicit reopen only) |
   | `cancelled` | terminal |

9. Add plan lint checks:

   - required frontmatter fields exist
   - plan IDs are unique
   - `status` values are valid
   - referenced files exist
   - referenced symbols exist
   - referenced context pages resolve
   - duplicate plan titles/slugs are warned
   - invalid status transitions are rejected
   - task statuses use the allowed vocabulary
   - batch IDs are consistent
   - strict mode does not allow oversized batches
   - evidence references resolve to the expected kind
   - malformed frontmatter produces actionable errors
   - `revision_type` is valid and consistent with accepted edits
   - `reapproval_required` is cleared only by a matching approval
   - task and batch dependency graphs are acyclic
   - engineering profile is valid
   - architecture style is valid
   - named standards and quality gates resolve
   - blocking quality gates are not silently absent
   - production work touching security, migration, API, or data has the relevant gates
   - product/production tasks have a testing strategy
   - frontmatter test contracts and body `Testing strategy` do not conflict
   - test IDs are unique and referenced only once per owning task
   - each implement test resolves to files and an applicable gate
   - each reuse test resolves to existing files and explains reuse
   - each omit test has a recorded reason
   - manual checks resolve to reviewable artifacts
   - a task cannot be done while a required implement test file is missing
   - task validation names a resolvable gate or an explicit manual-check artifact
   - vague validation such as "test it" or "verify" is rejected
   - bug-fix tasks have a reproduction test or a recorded reason why one is impossible
   - omitted new tests have a recorded reason
   - plain-language explanations exist when `plain_language` is enabled
   - approval metadata exists before `approved` or later statuses
   - approval metadata is not fabricated for command-gate outcomes
   - gate commands are argv lists with timeout and output limits
   - semantic post-approval edits are flagged as reapproval-worthy

10. Parser output should be usable as JSON by CLI and MCP:

   ```json
   {
     "schema_version": 1,
     "id": "...",
     "status": "...",
     "files": [],
     "symbols": [],
     "evidence": [],
     "engineering": {},
     "testing": {}
   }
   ```

11. Extend `doctor` with plan consistency checks.

12. Add tests for:

   - valid plan parsing
   - invalid frontmatter
   - missing referenced file
   - missing referenced symbol
   - duplicate plan ID
   - status transitions
   - invalid evidence kind
   - invalid task status
   - stale revision
   - invalid revision or content hash
   - invalid dependency reference
   - invalid risk value
   - invalid batch state transition
   - oversized batch in strict mode
   - passed batch made stale by changed input
   - stale batch counted as complete
   - missing batch id when multiple batches exist
   - invalid execution log event
   - passed batch without validation record
   - failed batch without diagnostic
   - semantic revision without reapproval
   - approval for a stale revision
   - task dependency cycle
   - batch dependency cycle
   - oversized plan graph
   - invalid gate outcome
   - stale gate remains attached to a completed batch
   - gate fingerprint missing for a passed command gate
   - command gate that never ran
   - review gate auto-marked as passed without review evidence
   - invalid engineering profile
   - missing blocking gate
   - missing plain-language explanation
   - missing testing strategy for non-trivial implementation
   - frontmatter/body test conflict
   - duplicate test ID
   - validation column with no executable gate or manual-check artifact
   - deferred test with no reason
   - implement test with missing file
   - implement test with missing gate
   - reuse test without existing file or reason
   - required test omitted without reason
   - task done while required test file is missing
   - approved plan without approval metadata
   - command gate marked passed without run evidence
   - review gate marked passed without reviewer evidence
   - `plan gate set` attempts to mark command or review gate as passed
   - gate manifest drift after approval
   - semantic post-approval edit without reapproval

### Files

| File | Change |
|---|---|
| `src/codeatlas/plans.py` | add plan model/parser/linter |
| `src/codeatlas/cli.py` | add `plan` command group |
| `src/codeatlas/consistency.py` | add plan checks |
| `tests/test_plan_engine.py` | add tests |

### Exit criteria

- [ ] Plan schema is documented.
- [ ] Plan files can be parsed and linted.
- [ ] `doctor` reports invalid plans.
- [ ] Existing behavior does not regress.

### Migration rule

Existing Markdown plan files are allowed to remain valid only if they can be upgraded to `schema_version: 1` without losing meaning. If they cannot, `doctor` should mark them as legacy and suggest migration instead of silently ignoring them.

## Phase 1: Minimal plan engine and `plan-artifacts` Skill

### Goal

Make it easy for an agent to create a plan that is structured, evidence-backed, and executable later.

### Tasks

1. Add CLI commands:

   ```bash
   codeatlas plan new <slug>
   codeatlas plan show <plan-id> --view summary|execution|engineering|evidence|graph|full
   codeatlas plan status
   codeatlas plan lint
   codeatlas plan transition <plan-id> <status>
   codeatlas plan approve <plan-id>
   codeatlas plan revise <plan-id>
   codeatlas plan diff <plan-id> --from-revision <n>
   codeatlas plan task set <plan-id> <task-id> <status>
   codeatlas plan batch set <plan-id> <batch-id> <status>
   codeatlas plan gate run <plan-id> <batch-id> <gate-id>
   codeatlas plan gate review <plan-id> <batch-id> <gate-id>
   codeatlas plan gate set <plan-id> <batch-id> <gate-id> <outcome>
   ```

2. `plan new` should create:

   ```text
   docs/plans/YYYY-MM-DD-<slug>.md
   ```

   with the Phase 0 frontmatter and body skeleton.

3. `plan status` should list plans grouped by:

   - `draft`
   - `approved`
   - `executing`
   - `blocked`
   - `done`
   - `cancelled`

   It should also show non-blocking warnings for:

   - `reapproval_required`
   - batches requiring revalidation
   - required tests not yet implemented
   - omitted tests with recorded reasons

4. `plan lint` should run the Phase 0 checks.

5. Create the `plan-artifacts` Skill with:

   - `SKILL.md`
   - `assets/plan-template.md`
   - `agents/openai.yaml`

   The Skill is only an adapter. The same plan engine should later be usable through CLI, MCP, and other agent clients without depending on Codex-specific behavior.

6. The Skill must enforce:

   - trigger only for non-trivial tasks
   - skip planning when the user says `just do it`
   - read CodeAtlas evidence before writing the plan
   - generate the plan file
   - stop for approval
   - execute only after approval
   - implement in validated batches
   - request durable approval before implementation
   - select an engineering profile based on task risk and affected surfaces
   - include only the adaptive engineering sections that apply to the task
   - attach executable quality gates to batches
   - decide whether tests will be added, updated, or omitted before implementation starts
   - place behavior-level tests in the same batch as the implementation when practical
   - generate the plan body from tables and structured dependencies
   - render a derived task/batch graph when more than one batch or dependency exists
   - explain non-obvious engineering requirements in plain language when requested
   - update task status during execution
   - run `codeatlas update .` and `codeatlas doctor` after code changes

7. Add `AGENTS.md` guidance:

   - non-trivial tasks should use `plan-artifacts`
   - plans live in `docs/plans/`
   - plans must cite CodeAtlas evidence
   - execution must update the plan and history

### Files

| File | Change |
|---|---|
| `src/codeatlas/cli.py` | add plan subcommands |
| `src/codeatlas/plans.py` | extend create/list/lint behavior |
| `docs/plans/` | plan output directory |
| `AGENTS.md` | document workflow |
| Codex skill directory | add `plan-artifacts` skill |

### Exit criteria

- [ ] `plan new` creates a valid plan file.
- [ ] `plan lint` catches invalid plans.
- [ ] `plan status` lists current plans.
- [ ] `plan show`, `plan transition`, and batch updates use the canonical schema.
- [ ] Bounded plan views and the derived dependency graph render without loading unnecessary sections.
- [ ] `plan revise` and `plan diff` distinguish semantic edits from state updates.
- [ ] Task status updates use the canonical command and reject stale revisions.
- [ ] Stale plan writes are rejected.
- [ ] `plan approve` records approver, basis, time, and engineering manifest hashes.
- [ ] Skill generates evidence-backed plans.
- [ ] Skill selects and records an adaptive engineering profile.
- [ ] Engineering gates are attached to the correct batches.
- [ ] Testing strategy identifies changed behavior and tests before implementation starts.
- [ ] Structured test contracts can be linted for missing files, missing gates, and unexplained omissions.
- [ ] Command gates run through the engine and review gates require evidence.
- [ ] Plain-language explanations are available without replacing machine-readable gate data.
- [ ] Agent stops for approval before implementation.
- [ ] A semantic change after approval blocks new batch execution until reapproved.
- [ ] Agent stops after each batch when validation or review is required.
- [ ] Post-execution update and doctor are enforced by convention.

## Phase 2: `plan context` retrieval

### Goal

Let the agent ask CodeAtlas for relevant project context before planning.

### Tasks

1. Add:

   ```bash
   codeatlas plan context "<task description>"
   ```

2. Add MCP tool:

   ```text
   plan_context(query, root?)
   ```

3. First implementation should combine:

   - FTS symbol search
   - module detail lookup
   - symbol history
   - file dependency graph
   - call graph neighbors
   - existing context pages
   - applicable engineering profiles and reusable quality gates
   - project convention files

4. Output should include:

   ```json
   {
     "query": "add token refresh flow",
     "generated_at": "...",
     "index_version": 42,
     "summary": "...",
     "evidence": [],
     "suggested_pages": [],
     "engineering": {
       "suggested_profile": "product",
       "applicable_gates": [],
       "architecture_boundaries": []
     },
     "impact_scope": {
       "files": [],
       "symbols": []
     }
   }
   ```

5. Support Markdown and JSON output.

6. Cap output size:

   - use the existing context budget model
   - return the smallest useful evidence set
   - mark omitted results explicitly
   - include `tokens`, `truncated`, and `reasons` in JSON output

7. Every evidence item must include:

   - `evidence_id`
   - `kind`
   - `ref`
   - `reason`
   - `confidence`
   - `stale`
   - `source_path`

8. If no index exists, return a bootstrap hint instead of pretending to retrieve evidence.

9. If evidence is stale because files changed after the last scan, mark it `stale: true` rather than suppressing it silently.

10. Rank evidence by:

   - exact symbol match
   - FTS score
   - call graph proximity
   - file dependency proximity
   - recent history relevance
   - match against architectural roles and convention names

11. Tie-breakers must be deterministic:

   - exact name match first
   - shorter qualified name second
   - lexicographic path third
   - stable evidence ID last

### Files

| File | Change |
|---|---|
| `src/codeatlas/plans.py` | add context retrieval |
| `src/codeatlas/service.py` | expose service-level API |
| `src/codeatlas/cli.py` | add `plan context` |
| `src/codeatlas/mcp_server.py` | add MCP tool |
| tests | add retrieval tests |

### Exit criteria

- [ ] Natural-language task returns relevant evidence.
- [ ] Output can be inserted into a plan file.
- [ ] Agent no longer needs to browse many files before planning.
- [ ] No external LLM is required.

## Phase 3: Plan-aware `update` impact reporting

### Goal

After code changes, tell the agent which open plans are affected.

### Tasks

1. Add:

   ```bash
   codeatlas plan impact <plan-id>
   ```

2. During `codeatlas update .`, detect affected open plans by intersecting:

   - changed files
   - changed symbols
   - plan `files`
   - plan `symbols`
   - `refs`
   - `call_edges`

   Only these statuses count as open:

   - `approved`
   - `executing`
   - `blocked`

   `done` plans are not open for new impact work, but their required validation is still checked. If later changes invalidate a done plan's gate fingerprint, CodeAtlas reports stale validation and leaves explicit reopening to the user.

3. Distinguish impact levels:

   | Level | Meaning |
   |---|---|
   | `direct` | A changed file or symbol is explicitly listed in the plan. |
   | `indirect` | A dependency, caller, or callee of a planned symbol changed. |
   | `possible` | Heuristic graph or FTS evidence suggests relevance. |

   Impact rules:

   - graph traversal must have a bounded depth
   - retrieval must have a bounded candidate count
   - `possible` must include a confidence score
   - `possible` should warn but never block execution by itself
   - `direct` impact should be shown even if the plan is stale
   - stale evidence must be labeled, not silently removed
   - impact reporting must not fail the whole `update` command when one plan is malformed; the malformed plan should appear in a warnings section

4. Output format:

   ```text
   Updated 3 file(s), 4 symbol change(s).

   Affected open plans:
   - 2026-09-16-auth-refresh-flow
     - batch B2
      - auth/refresh-service.ts
     - AuthService.refresh
   ```

   When a direct change intersects a passed command gate's `input_state_hash`, `update` must mark that gate and batch `stale` and print:

   ```text
   Revalidation required:
   - 2026-09-16-auth-refresh-flow batch B2 gate unit-tests
   ```

5. Add `doctor` checks for:

   - plan references files that no longer exist
   - plan references symbols that no longer exist
   - plan is `executing` but no longer has open tasks
   - plan is `blocked` without a blocker reason
   - a batch exceeded strict mode limits
   - an executing batch has no recorded validation result
   - a batch passed while a blocking engineering gate is failed or missing
   - a passed gate has a missing or stale input-state fingerprint
   - a batch is `done` or `passed` while a blocking gate is `stale`
   - a production plan lacks security, migration, compatibility, or API gates for the relevant work
   - an architecture decision is contradicted by the referenced module boundary

6. Add tests for:

   - changed file matches plan
   - changed symbol matches plan
   - indirect dependency matches plan
   - no plan affected
   - affected plan reports the correct batch
   - changed input marks a passed blocking gate stale
   - unchanged input keeps a passed gate valid
   - gate manifest drift is reported
   - semantic post-approval edit reports reapproval required

### Files

| File | Change |
|---|---|
| `src/codeatlas/plans.py` | add impact logic |
| `src/codeatlas/indexer.py` | integrate update reporting |
| `src/codeatlas/cli.py` | add `plan impact` |
| `src/codeatlas/consistency.py` | add checks |
| tests | add impact tests |

### Exit criteria

- [ ] `update` reports affected open plans.
- [ ] `plan impact` works independently.
- [ ] Impact reporting can identify the affected batch.
- [ ] Impact reporting identifies affected engineering gates and architecture boundaries.
- [ ] Broken plan references are detectable.
- [ ] Agent can resume from the correct plan after interruption.

## Phase 4: Task/session-scoped context VM

### Goal

Prevent multiple tasks or terminals from overwriting each other's working set.

### Tasks

1. Add scope fields to working set:

   - `session_id`
   - `plan_id`
   - optional `batch_id`

2. Extend context commands:

   ```bash
   codeatlas context load <page> --plan <plan-id>
   codeatlas context status --plan <plan-id>
   codeatlas context evict <page> --plan <plan-id>
   ```

   Also support:

   ```bash
   codeatlas context load <page> --session <session-id>
   codeatlas context load <page> --plan <plan-id> --batch <batch-id>
   ```

   Scope precedence is `batch > plan > session > global`. If more than one scope is supplied, the most specific scope owns the page.

3. Preserve a global view for compatibility.

4. Use SQLite transactions for writes.

5. Define scope ownership:

   - `session_id` identifies one agent session or terminal.
   - `plan_id` identifies the task context.
   - A page may belong to a plan, a session, or both.
   - Orphaned scope records must be cleanable without deleting global history.
   - Scope writes use short-lived leases instead of long-held global locks.
   - A lease must include an owner, expiration time, and explicit release operation.

6. Prevent eviction of pages owned by another active plan.

7. Show stale/gone state per plan.

8. Add tests for:

   - scoped load
   - scoped status
   - scoped eviction
   - cross-plan isolation
   - batch-scoped isolation when a batch id is provided
   - concurrent writes
   - invalid or conflicting scope combinations

### Files

| File | Change |
|---|---|
| `src/codeatlas/models.py` | extend working set entry |
| `src/codeatlas/storage.py` | migrate schema |
| `src/codeatlas/memory.py` | scope-aware logic |
| `src/codeatlas/cli.py` | scoped commands |
| `src/codeatlas/mcp_server.py` | scoped MCP parameters |

### Exit criteria

- [ ] Multiple plans can have separate working sets.
- [ ] A terminal cannot erase another plan's context.
- [ ] Global behavior remains backward compatible.
- [ ] Scope precedence is deterministic and documented.
- [ ] Stale/gone status is visible per plan.

## Phase 5: Optional description enrichment

### Goal

Improve descriptions without making LLMs mandatory.

### Tasks

1. Keep `RuleSummarizer` as the default.

2. Add an enrichment interface:

   ```python
   class Enricher:
       def enrich_symbol(self, symbol, context): ...
       def enrich_file(self, record, context): ...
   ```

3. Generate optional fields:

   - `purpose`
   - `inputs`
   - `outputs`
   - `side_effects`
   - `related_modules`
   - `risk_notes`
   - `confidence`
   - `source`

4. Cache enriched results by file hash and symbol body hash.

5. Allow local model, LLM, or no-op enricher.

6. Add explicit cost controls:

   - maximum symbols enriched per run
   - maximum tokens per symbol
   - cache hit requirement
   - offline no-op mode
   - provenance for every generated field
   - plain-language mode that explains technical purpose without inventing guarantees

7. Prefer enriching only high-value symbols:

   - high fan-in
   - high fan-out
   - public API
   - core service
   - frequently changed symbols

### Files

| File | Change |
|---|---|
| `src/codeatlas/summarizer.py` | add enricher interface |
| `src/codeatlas/storage.py` | optional metadata columns/tables |
| `src/codeatlas/markdown.py` | render enriched fields |
| tests | add enrichment fallback tests |

### Exit criteria

- [ ] Core indexing works without LLM.
- [ ] Enrichment is cacheable.
- [ ] Enriched output has provenance and confidence.
- [ ] Rule summaries remain available as fallback.
- [ ] Plain-language enrichment does not override exact commands, evidence, or gate status.

## Phase 6: Semantic search and embeddings

### Goal

Allow natural-language retrieval across code and plans.

### Tasks

1. First build a small retrieval benchmark:

   - 10-30 realistic task descriptions
   - expected modules, files, and symbols
   - precision@k and recall@k targets

2. Add local embedding support.

3. Store vectors in SQLite or a local vector extension.

4. Index:

   - symbols
   - files
   - modules
   - history records
   - plan files

5. Blend search signals:

   - FTS exact/keyword score
   - embedding similarity
   - graph proximity
   - recency
   - plan relevance

6. Return hybrid results with reason labels.

7. Embeddings must be optional:

   - disabled by default
   - local-first
   - deterministic fallback to FTS and graph retrieval
   - cache vectors by file and symbol version
   - never send repository content to a remote service unless explicitly configured

### Files

| File | Change |
|---|---|
| `src/codeatlas/search.py` | add hybrid retrieval |
| `src/codeatlas/storage.py` | vector storage |
| `src/codeatlas/cli.py` | extend query |
| `src/codeatlas/mcp_server.py` | extend search tool |

### Exit criteria

- [ ] Natural-language task finds relevant code.
- [ ] Search results include explanation of why each item matched.
- [ ] Embeddings are optional and local-first.
- [ ] FTS remains the fallback.

## Phase 7: Git-aware rollback

### Goal

Make recovery safe without replacing Git.

### Tasks

1. Record update context:

   - commit before change
   - commit after change, when available
   - dirty diff before update
   - plan ID
   - changed files/symbols

2. Add:

   ```bash
   codeatlas plan rollback <plan-id>
   codeatlas plan rollback <plan-id> --batch <batch-id>
   ```

3. Default behavior:

   - generate reverse patch
   - show preview
   - require confirmation
   - apply only after explicit approval
   - record rollback evidence in the plan execution log
   - update the affected batch to `stale`, `blocked`, or `failed`, not `done`
   - mark affected command-gate results `stale` because their recorded input state no longer exists

   Additional guardrails:

   - no automatic rollback
   - no rollback across unrelated plans by default
   - dry-run mode must be available
   - generated reverse patch must be written to a reviewable location
   - conflicted restores must stop and require manual resolution

4. Use own snapshot only when Git is unavailable.

5. Extend doctor to check:

   - history and rollback records align
   - plan and change records align
   - no restore record points to missing diff

### Files

| File | Change |
|---|---|
| `src/codeatlas/rollback.py` | new rollback layer |
| `src/codeatlas/storage.py` | rollback records |
| `src/codeatlas/cli.py` | rollback commands |
| `src/codeatlas/consistency.py` | rollback checks |

### Exit criteria

- [ ] Rollback is reviewable before execution.
- [ ] Git remains the preferred recovery mechanism.
- [ ] Plan, history, and rollback records are consistent.
- [ ] Rolled-back batches and gates do not retain stale `passed` evidence as current proof.
- [ ] Dangerous restores require explicit approval.

## Phase 8: Watcher, CI, and language expansion

### Goal

Turn CodeAtlas into a durable development infrastructure component.

### Tasks

1. Add optional file watcher daemon:

   - debounced updates
   - update only changed files
   - avoid running during active edits

2. Add GitHub Action mode:

   - generate architecture diff on PR
   - list affected plans
   - list affected symbols
   - list affected engineering gates
   - fail the PR when a blocking engineering gate fails
   - compare the current gate manifest with the approved manifest hash
   - rerun command gates in CI; do not trust local gate output as the only evidence
   - require review-gate evidence instead of rerunning a review automatically
   - report architecture drift separately from lint failures
   - comment only on meaningful changes

3. Expand tree-sitter language support:

   - Go
   - Rust
   - Java

4. Add MCP output shaping:

   - task-specific module detail
   - plan-specific subgraphs
   - token-capped responses

5. Watcher constraints:

   - disabled by default
   - debounce file events
   - ignore `.codeatlas/`, `node_modules`, build output, and generated files
   - respect `.gitignore`
   - avoid update storms
   - expose clear start/stop/status commands

### Exit criteria

- [ ] Index can refresh without manual invocation.
- [ ] PR review can show architecture and plan impact.
- [ ] CI can enforce blocking engineering gates.
- [ ] CI detects gate-manifest drift and unreviewed review gates.
- [ ] Additional languages use the same artifact contract.
- [ ] Agent output remains token-conscious.

## First implementation slice

The MVP must not land as one large PR. Split Slice 1 into independently reviewable PRs:

| PR | Contents | Exit condition |
|---|---|---|
| `1a-plan-contract` | Phase 0 schema, parser, `plan new`, `plan lint`, `plan status`, `plan show --view summary/full`, template, valid/invalid fixture tests | A clean plan can be created and an invalid plan is rejected with stable errors. |
| `1b-plan-workflow` | Revision/conflict checks, `plan approve`, `plan revise`, `plan diff`, bounded `engineering/execution/evidence` views, minimal derived projection | Approval and semantic revision are durable and inspectable. |
| `1c-execution-quality` | Engineering profile/gate references, batch/task transitions, execution logs, `gate run/review/set`, and structured test contracts with lint | A batch can be executed, validated, and tested with recorded evidence. |
| `1d-memory-graph` | Input fingerprints/stale marking, task/batch Mermaid graph, `codeatlas update .` integration, doctor checks, `AGENTS.md` guidance, minimal Skill adapter | A real task can be planned, approved, implemented in batches, invalidated by later changes, and resumed. |

The Skill may be introduced in `1a` as a thin template adapter, but should not become a source of plan semantics. `1c` and `1d` are still part of the MVP; do not market the workflow as complete before gate evidence and stale-result detection exist.

### Implementation kickoff order

Current code inspection on 2026-09-17 confirms that the repository has no `src/codeatlas/plans.py`, no `plan` CLI command group, and no plan projection tables. Therefore, implementation should start with the pure artifact layer rather than persistence.

| Step | Action | Owner | Definition of done |
|---|---|---|---|
| 0 | Human approves [2026-09-17-codeatlas-1a-plan-contract.md](../plans/2026-09-17-codeatlas-1a-plan-contract.md) | user | Plan status becomes `approved`; no implementation starts before approval. |
| 1 | Implement `1a-plan-contract` B1: pure parser/linter | agent | Plan tests T-001..T-006 pass; no CLI/Rich/Typer dependency in `plans.py`. |
| 2 | Implement `1a` B2: `plan new/show/status/lint` | agent | T-007..T-009 pass; JSON output and exit codes are stable. |
| 3 | Implement `1a` B3: template/docs polish | agent | Full pytest and doctor pass; plan artifact contract is documented. |
| 4 | Review and merge `1a` | user | PR meets the 1a exit condition. |
| 5 | Implement `1b-plan-workflow` | agent | Approval, revise, diff, and bounded views work with durable revisions. |
| 6 | Implement `1c-execution-quality` | agent | Batch/task transitions and gate/test evidence work. |
| 7 | Implement `1d-memory-graph` | agent | Fingerprint/stale marking, graph, update, doctor, AGENTS/Skill guidance work. |

Every implementation batch must end with the plan-specific tests, the full test suite, `codeatlas update .`, and `codeatlas doctor`. If a batch fails validation, stop and record the result in the active plan before starting another batch.

## Compatibility matrix

The core plan engine should be tested against these degraded environments:

| Case | Expected behavior |
|---|---|
| FTS unavailable | Fall back to LIKE search and graph traversal. |
| No Git repository | Disable Git-aware rollback but retain plan/history functionality. |
| No YAML parser | Reject plan writes with a clear dependency message, or use a minimal built-in parser if practical. |
| Malformed plan | Preserve the file; `doctor` reports the error instead of silently deleting or rewriting it. |
| Concurrent plan edits | Reject stale revision and require re-read. |
| Windows paths | Use repo-relative POSIX paths internally. |
| Symlinked file outside root | Reject or resolve safely; never index outside the workspace boundary. |
| Large plan repository | Cap retrieval, status, and impact output. |
| Missing symbol after refactor | Mark evidence stale or gone; do not erase history. |
| No custom engineering profiles | Use safe built-in fallback profiles and warn that project-specific standards are absent. |
| Quality-gate command unavailable | Record `not-run` with the failure reason; never silently mark a blocking gate as passed. |
| Gate output is very large | Truncate and store a digest with a bounded diagnostic; never exhaust memory or context. |
| Gate command times out | Kill or abandon the runner safely, record `failed`/`not-run` according to policy, and preserve diagnostics. |
| Engineering config changes after approval | Report manifest drift and require explicit reapproval for affected blocking gates. |
| Agent tries to assert a command gate passed | Reject with `GATE_KIND_INVALID`; only runner evidence can produce that outcome. |
| Relevant code changes after a gate passes | Recompute the input fingerprint, mark gate and batch stale, and require revalidation. |
| Later change invalidates a done plan | Report stale validation; do not silently reopen or preserve a false `done`. |
| Plan state writing disabled during update | Report stale evidence in JSON and doctor; leave Markdown unchanged. |
| Planned test file is missing when task is done | Block the task transition and report `TEST_CONTRACT_MISMATCH`. |
| Manual check artifact is missing | Block manual-test completion and require a reviewable artifact. |
| Plan graph is very large | Cap rendered nodes and edges; state that the graph is truncated. |
| Hand edit bypasses `plan revise` | Re-run the semantic diff classifier on lint and set `reapproval_required` when needed. |

## Observability and quality gates

Each phase should expose a small, measurable signal instead of relying only on subjective review.

| Signal | Purpose |
|---|---|
| `plans_total` | Count of plans by status. |
| `plans_lint_failures` | Detect malformed or stale plans. |
| `evidence_hit_rate` | Fraction of plans with resolvable CodeAtlas evidence. |
| `batch_size_distribution` | Detect plans that allow oversized or fragmented batches. |
| `batch_validation_failures` | Detect execution steps that are too large or unstable. |
| `plan_write_conflicts` | Detect concurrent or stale plan updates. |
| `plan_transition_rejections` | Detect invalid workflow usage. |
| `plan_projection_drift` | Detect Markdown and SQLite disagreement. |
| `impact_hits` | Number of code changes linked to open plans. |
| `retrieval_latency` | Keep `plan context` interactive. |
| `retrieval_truncation_rate` | Detect evidence sets that are too large or too noisy. |
| `context_scope_conflicts` | Detect concurrent context overwrites. |
| `stale_context_pages` | Detect stale/gone pages by scope. |
| `engineering_gate_failures` | Detect failed tests, checks, reviews, or safety gates. |
| `engineering_gate_deferrals` | Make skipped recommended rules visible. |
| `architecture_drift_warnings` | Detect changes that cross or contradict declared boundaries. |
| `missing_quality_profiles` | Detect projects without reusable engineering defaults. |
| `plain_language_coverage` | Detect named engineering concepts that lack user-facing explanation. |
| `gate_manifest_drift` | Detect approved plans whose engineering contract changed. |
| `reapproval_required_events` | Detect semantic post-approval scope/risk/architecture edits. |
| `quality_gate_timeouts` | Detect slow or hung validation commands. |
| `gate_output_truncations` | Detect noisy gates that need output tightening. |
| `fabricated_gate_attempts` | Detect attempts to mark command gates passed without execution. |
| `stale_validation_results` | Detect passed work whose inputs changed after validation. |
| `done_plan_stale_validation` | Detect completed plans whose evidence no longer applies. |
| `update_plan_write_failures` | Detect locking, revision conflict, or disabled state writing during update. |
| `gate_input_mismatches` | Detect command gates whose fingerprint cannot be reproduced. |
| `testing_strategy_missing` | Detect non-trivial tasks that do not say how behavior will be tested. |
| `deferred_tests` | Make postponed tests visible instead of silently accepted. |
| `test_contract_mismatches` | Detect planned tests whose files or gates do not resolve. |
| `untested_behavior_completions` | Detect done tasks without required test coverage or approved omission. |
| `semantic_revisions_after_approval` | Detect post-approval scope/risk/architecture changes. |
| `reapproval_block_rate` | Detect how often approved plans change materially during execution. |
| `plan_graph_truncations` | Detect plans whose dependency diagrams are too large for safe rendering. |
| `update_duration` | Catch performance regressions. |
| `doctor_failures` | Track invariant health. |

Minimal implementation can be CLI-reported counters in SQLite; a full metrics backend is not required in the first slice.

## Security and privacy

| Concern | Rule |
|---|---|
| Workspace boundary | Index and resolve files only under the selected project root unless explicitly configured. |
| Secrets | Respect ignore files; avoid storing secret-bearing file bodies in new indexes. |
| MCP exposure | Do not expose destructive operations without explicit flags and confirmation. |
| Network | Core indexing, planning, retrieval, and doctor must work offline. |
| LLM enrichment | Disabled by default; all external calls require explicit user configuration. |
| Embeddings | Prefer local models; remote embedding must be opt-in. |
| Rollback | Generate preview patches; never silently rewrite working-tree files. |
| Symlinks and paths | Normalize paths and reject escapes outside the project root. |
| YAML parsing | Use safe parsing only; never execute content embedded in plan files. |
| Plan file size | Reject or truncate abnormally large plan files instead of exhausting memory. |
| Plan content injection | Treat plan content as data; do not execute shell commands found in Markdown. |
| Prompt injection through plans | Treat plan instructions as task data, not as permission to bypass approval, gates, or workspace boundaries. |
| Gate execution | Use trusted argv configuration, timeouts, output caps, sandbox-safe working directories, and no shell interpolation. |
| Approval integrity | Store durable approval metadata and engineering manifest hashes; conversational approval is insufficient by itself. |

## Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Plan schema becomes too rigid | Agents stop using it | Keep required fields minimal; make optional fields explicit. |
| Plan files drift from code | Impact reporting becomes wrong | Use lint, doctor, and update-time impact checks. |
| Concurrent plan edits | Agents overwrite each other | Revision/hash checks and plan transition commands. |
| Batch state becomes noisy | Users lose track of execution | Keep batch states limited and derive summaries in `plan status`. |
| Batch control becomes bureaucratic | Agents slow down and users get approval fatigue | Use adaptive mode by default; reserve strict mode for high-risk work. |
| Engineering-by-default becomes ceremony | Non-engineers abandon planning | Use tiered profiles, adaptive sections, short explanations, and required gates only for real risk. |
| Quality gates pretend to prove more than they do | False confidence | Label command gates and review gates separately, record outcomes, and never auto-pass review gates. |
| Tests are postponed until after implementation | Defects are found late and behavior coverage is guessed | Require an adaptive testing strategy and attach behavior tests to the implementation batch. |
| Test plans remain prose that cannot be verified | Agents claim coverage without adding tests | Use structured test IDs, files, owning tasks, gate references, and lint/doctor checks. |
| Coverage targets encourage meaningless tests | Test suite becomes noisy without catching regressions | Focus tests on changed behavior, error paths, and regression targets; treat global coverage as informational. |
| Custom profiles become inconsistent across agents | Automation and prompts disagree | Store profiles as local, versioned configuration consumed by Skill, CLI, MCP, and CI. |
| Agents fabricate approvals or gate passes | Unsafe work appears validated | Durable approvals, manifest hashes, runner evidence, and stable gate errors. |
| Old test evidence proves changed code | False confidence and unsafe completion | Input-state fingerprints, stale gate outcomes, and revalidation before `done`. |
| Update automatically edits plan files | Users lose trust or stale writes conflict | Restrict to state-only changes through the canonical writer; skip malformed/conflicted plans and support report-only mode. |
| Gate commands become a local execution surface | Malicious or accidental command execution | Trusted argv configuration, allowlists, timeouts, output caps, and no content-derived commands. |
| Plan files become too large for agents | Higher token cost and lower reliability | Bounded views, capped retrieval, execution-view defaults, and explicit omission metadata. |
| Reapproval workflow becomes annoying | Users skip or rubber-stamp approvals | Limit reapproval to semantic changes; make `plan diff` short and explain exactly what changed. |
| Plan diagrams drift from the plan | Users see an incorrect mental model | Generate diagrams from structured dependencies; lint cycles and never parse hand-written diagrams as source data. |
| Retrieval returns irrelevant evidence | Agent confidence drops | Rank by graph + FTS, label evidence, and cap output. |
| Context VM scoping complicates CLI | Backward compatibility breaks | Keep global view as default; add scopes opt-in. |
| LLM summaries hallucinate | Project memory becomes misleading | Keep rule summaries canonical; label provenance and confidence. |
| Embeddings add hidden cost | Users lose trust | Local-first, cached, disabled by default, benchmark-gated. |
| Rollback destroys work | Data loss | Review-first reverse patch and explicit approval. |
| Watcher causes update storms | Performance degrades | Debounce, ignore rules, disabled-by-default. |
| Skill and core become coupled | Other agents cannot use the workflow | Keep plan logic in core; Skill is only an adapter. |

## Rollout policy

1. Ship Slice 1 behind normal behavior, not as a hard requirement for every task.
2. Keep existing `scan`, `update`, `query`, `history`, and `context` commands backward compatible.
3. Add new plan commands only after their exit criteria are tested.
4. Use `doctor` as the upgrade gate: if plan invariants fail, indexing should still work, but planning should warn.
5. Do not enable watcher, embeddings, enrichment, or rollback by default.
6. Start batch control in `adaptive` mode; enable `strict` mode only for high-risk plan types.
7. Start engineering-by-default with `product`-style quality gates and plain-language explanations; do not force `production` ceremony on every task.
8. Treat missing reusable profiles as a warning, not a hard failure, until the built-in fallback profiles are stable.
9. Treat revision conflict detection as part of Slice 1, not a later optimization.
10. Use feature flags or configuration for new surfaces; do not make plan commands mandatory for existing workflows.
11. Keep command-gate execution behind explicit trusted configuration and begin with a very small allowlisted set.
12. Enable durable approval and gate-manifest checks before batch execution is allowed to proceed by default.
13. Use bounded plan views for MCP and agent-facing output so resumed sessions do not reload the whole plan unnecessarily.

## Roadmap change policy

This roadmap should be treated as implementation-ready at v13. Further version changes should be evidence-driven, not another abstract review:

1. After `1a-plan-contract`, changes to the schema must cite a failing parser/lint case.
2. After `1b-plan-workflow`, workflow changes must cite a failed approval, revision, conflict, or resume scenario.
3. After `1c-execution-quality`, gate or testing changes must cite a real batch-validation failure.
4. After `1d-memory-graph`, staleness, impact, or diagram changes must cite a real update/doctor finding.
5. Do not add a new product area unless an MVP end-to-end workflow has passed first.

## Definition of success

- [ ] Agent starts tasks from CodeAtlas evidence, not blind file browsing.
- [ ] Plans are structured and machine-checkable.
- [ ] Plan state is reconstructable from Markdown and queryable from the derived projection.
- [ ] Interrupted work can resume from a plan file.
- [ ] Code changes are linked back to open plans.
- [ ] Context VM is scoped by task/session.
- [ ] Agent work is split into validated batches instead of one large multi-file sweep.
- [ ] Non-trivial plans carry an adaptive engineering profile.
- [ ] Architecture decisions, applicable gates, and safety requirements are visible before implementation.
- [ ] Blocking quality gates are recorded and enforced per batch.
- [ ] Approvals are durable, attributable, and tied to the approved engineering manifest.
- [ ] Command-gate results come from execution evidence, not agent assertion.
- [ ] Gate evidence is invalidated when its recorded input state changes.
- [ ] A plan cannot reach `done` while a blocking gate or batch is stale.
- [ ] Semantic post-approval edits create a reapproval decision instead of silently changing scope.
- [ ] Plain-language explanations help non-engineers understand why each gate matters.
- [ ] Large plans can be rendered in bounded summary, execution, and engineering views.
- [ ] Non-trivial plans identify new/updated tests before implementation begins.
- [ ] Planned tests are machine-checkable against files, owning batches, and quality gates.
- [ ] Tests proving a batch are written or updated with that batch, not deferred by default.
- [ ] A done plan cannot hide stale validation after later code changes.
- [ ] Stale plan writes are state-only, canonical, and safe when update integration runs.
- [ ] Task and batch dependency diagrams are derived from structured plan data.
- [ ] Concurrent plan edits are detected rather than silently overwritten.
- [ ] Doctor can detect broken plans and stale context.
- [ ] Advanced AI features remain optional.
