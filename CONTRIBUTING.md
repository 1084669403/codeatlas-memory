# Contributing

Thanks for helping improve CodeAtlas. This project uses source-based
development, local tests, and durable plan records for non-trivial changes.

## Development setup

```bash
git clone https://github.com/1084669403/codeatlas-memory
cd codeatlas-memory
uv sync --extra mcp
uv run pytest
```

## Before you open a pull request

- Start from a focused branch.
- Add or update tests for behavior or documentation contracts you change.
- Run `uv run pytest`.
- Run `codeatlas update .` after changing indexed source files.
- Run `codeatlas doctor` when index consistency may be affected.
- Keep generated `.codeatlas/state.db`, `.codeatlas/detail/`, `.venv/`, and
  test scratch files out of the commit.
- Describe the user-visible change and validation in the pull request.

For a behavior change, include a short rationale and note any intentional
compatibility impact. Do not add publishing, semantic search, rollback,
watchers, or other large roadmap features to an unrelated pull request.

## Durable plan workflow

Use the durable plan workflow for changes that cross several files, alter a
workflow contract, or need resumable execution:

1. Retrieve relevant context with `codeatlas plan context "<task>" --json`.
2. Create a plan with `codeatlas plan new <slug> . --json`.
3. Have a human record approval through `codeatlas plan approve`.
4. Execute one batch at a time and run its quality gate.
5. Complete the batch only after validation passes.

Markdown files under `docs/plans/` are authoritative. Derived state under
`.codeatlas/plans/` is not a second source of truth.

## Code review expectations

Reviewers should look for focused scope, accurate documentation, tests tied to
the changed behavior, clean generated-artifact handling, and validation evidence
that matches the current change.
