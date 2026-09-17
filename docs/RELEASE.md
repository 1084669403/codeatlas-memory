# Release checklist / 发布检查单

Steps are ordered; do not skip ahead. / 步骤有先后顺序，不要跳步。

## 0. Prerequisites / 前置条件（一次性）

- [ ] GitHub repository exists and `main` is pushed:
      ```bash
      git remote add origin git@github.com:<org-or-user>/codeatlas-memory.git
      git push -u origin main
      ```
- [ ] `[project.urls]` in `pyproject.toml` points at the **real** repo
      (Repository / Issues are shown on the PyPI page — dead links hurt trust).
- [ ] CI is green on the pushed commit.
- [ ] PyPI account + API token (create at pypi.org → Account settings → API tokens).
- [ ] Package name `codeatlas-memory` is still free (checked 2026-09-15).

## 1. Version bump + tag

- [ ] Update `version` in `pyproject.toml` (SemVer; project is pre-1.0: 0.x.y).
- [ ] Commit, tag, push:
      ```bash
      git add pyproject.toml
      git commit -m "chore: release vX.Y.Z"
      git tag vX.Y.Z
      git push --tags
      ```

## 2. Build

```bash
uv build
```

- [ ] `dist/` contains one `.tar.gz` (sdist) and one `.whl` for the version.

## 3. Verify metadata

```bash
uvx twine check dist/*
```

- [ ] Both artifacts pass.
- [ ] Sanity-install into a scratch venv and run the CLI + MCP entry:
      ```bash
      uv venv /tmp/ca-test
      uv pip install --python /tmp/ca-test dist/codeatlas_memory-*.whl
      /tmp/ca-test/bin/codeatlas --help          # Windows: Scripts\codeatlas.exe
      /tmp/ca-test/bin/codeatlas --help          # mcp extra: reinstall with [mcp]
      ```

## 4. Upload

```bash
uvx twine upload dist/*
```

- [ ] Use a project-scoped API token (`--username __token__`).
- [ ] Check the PyPI page renders: README, classifiers, correct URLs.
- [ ] Test-install: `uvx --from "codeatlas-memory[mcp]" codeatlas-mcp --help`
      (stdio servers exit on EOF; verifying `--help` / import is enough).

## 5. Later: trusted publishing

Once the repo is public, replace manual uploads with a GitHub Actions job
using PyPI trusted publishing (no token in secrets) — add `pypi-publish`
step gated on tags.

## Post-release

- [ ] `codeatlas update .` on this repo so the release lands in
      `.codeatlas/history/`.
- [ ] `codeatlas doctor` passes.
