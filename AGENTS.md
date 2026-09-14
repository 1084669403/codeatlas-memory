# AGENTS.md — AI 使用约定 / AI Usage Conventions

> 本文件面向在本仓库（及任何用 CodeAtlas 索引过的仓库）工作的 AI 助手。
> This file is for AI assistants working in this repo (or any repo indexed by CodeAtlas).

## 双语约定 / Bilingual Conventions

### 1. 先读索引，再动手 / Read the index before you act

- 开始任务前先读 `CODEATLAS.md`（总览 + 4 张架构图：目录树 / 模块依赖 / 类继承 / 调用图（近似））。
  Read `CODEATLAS.md` first (overview + 4 diagrams: tree / deps / inheritance / call graph (approximate)).
- 需要单个模块细节时读 `.codeatlas/detail/<module>-*.md`，不要整仓通读。
  For one module's details, read `.codeatlas/detail/<module>-*.md`; do not read the whole repo.

### 2. 找符号用 query / Find symbols with query

```bash
codeatlas query <关键词>     # FTS5 trigram 全文检索 / full-text search
codeatlas history <符号>     # 符号演变链（自动跟随重命名）/ evolution chain (follows renames)
```

### 3. 大上下文用虚拟内存 / Use the context VM for large codebases

- 加载单页：`codeatlas context load <符号|文件>` —— stdout 直接输出 markdown 页（可管道）。
  Load one page: `codeatlas context load <symbol|file>` — markdown page on stdout (pipe-friendly).
- 程序化消费加 `--json`；歧义裸名返回 exit 2 与候选列表。
  Add `--json` for programmatic use; ambiguous bare names exit 2 with candidates.
- 查看驻留集与预算：`codeatlas context status`（底部有预算进度条）。
  Resident set & budget: `codeatlas context status` (progress bar at the bottom).
- 接近预算先淘汰：`codeatlas context evict <page|--all>`（`--all` 保留 pinned）。
  Near budget? Evict first: `codeatlas context evict <page|--all>` (keeps pinned).

### 4. 改完必须更新索引 / Always update the index after edits

```bash
codeatlas update .    # 增量更新 + 体级 diff 历史 / incremental update + body-level diff history
```

- 改动会记入 `.codeatlas/history/`：签名变更、重命名、以及"签名未变但函数体修改 +N/-M"。
  Changes land in `.codeatlas/history/`: signature edits, renames, and "signature-stable body edits +N/-M".

### 5. 索引可疑就体检 / Run doctor when the index looks off

```bash
codeatlas doctor      # 6 条一致性不变量 + 预算/解析率建议；违规 exit 1
```

### 6. 自查清单 / Self-check before you finish

- [ ] `codeatlas update .` 已运行且无报错 / ran clean
- [ ] 涉及的符号历史已生成（`.codeatlas/history/`）/ history written
- [ ] 大上下文任务用了 `context load` 而非整文件粘贴 / used `context load`, not whole-file dumps
- [ ] `codeatlas context status` 中无异常 stale/gone 堆积 / no abnormal stale/gone pile-up

## 已知限制 / Known Limitations

- 调用图为近似：装饰器调用、动态分派、高阶回调可能缺失或归因近似。
  Call graph is approximate: decorator calls, dynamic dispatch, higher-order callbacks may be missing/approximate.
- 两个终端并发写工作集是"最后写入胜出"（Phase 3 MCP 将加锁）。
  Concurrent working-set writes from two terminals are last-write-wins (locking comes with Phase 3 MCP).
