"""EN: Layered Markdown rendering: CODEATLAS.md overview + detail shards.
ZH: 分层 Markdown 渲染：CODEATLAS.md 总览 + .codeatlas/detail/ 分片。

EN: The overview stays at file granularity (size driven by file count, not
symbol count); full symbol-level detail goes to .codeatlas/detail/<module>.md
so AI tools can read one module on demand instead of the whole index.
ZH: 总览保持文件粒度（体积由文件数而非符号数决定）；符号级全量明细放
.codeatlas/detail/<module>.md，AI 按需读取单个模块而非整个索引。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .diagrams import build_all_diagrams
from .models import ScanResult
from .storage import Store


def _module_of(path: str) -> str:
    """Top-level directory of a POSIX path ('' for root files)."""
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else "(root)"


def _detail_filename(module: str) -> str:
    safe = hashlib.md5(module.encode("utf-8")).hexdigest()[:8]
    name = "root" if module == "(root)" else module.replace("/", "_")
    return f"{name}-{safe}.md"


def estimate_tokens(text: str) -> int:
    """CJK-aware token estimation for budget pruning.

    EN: CJK chars ~1 token each; other chars ~3.3 chars/token (code density).
    A flat len/4 undercounts Chinese by 3-4x — this estimator is required
    for --max-tokens to work with --lang zh output.
    ZH: CJK 字符约 1 token/字；其余约 3.3 字符/token（代码密度）。
    简单 len/4 会把中文低估 3-4 倍 —— --lang zh 输出必须用此估算器。
    """
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf")
    other = len(text) - cjk
    other_tokens = -(-other // 3) if other else 0
    return cjk + other_tokens if text else 0


def render_detail_files(
    store: Store, detail_dir: Path, lang: str = "en"
) -> dict[str, int]:
    """Write .codeatlas/detail/<module>.md shards; returns {module: symbol_count}.

    EN: grouped by top-level directory; each file header states entry count.
    Symbol rows carry everything AI needs: signature, params, returns,
    description, role, line, bases.
    ZH: 按顶层目录分组；每个文件头标注条目数。符号行包含 AI 所需全部信息：
    签名、参数、返回值、描述、角色、行号、基类。
    """
    detail_dir.mkdir(parents=True, exist_ok=True)
    # EN: clear stale shards first (files may have been deleted since last run).
    # ZH: 先清理过期分片（文件可能已被删除）。
    for old in detail_dir.glob("*.md"):
        old.unlink()

    rows = store.conn.execute(
        "SELECT f.path, f.language, f.role, s.qualified_name, s.name, s.kind, "
        "s.signature, s.params, s.returns, s.description, s.line, s.end_line, s.bases "
        "FROM symbols s JOIN files f ON f.path = s.file "
        "ORDER BY f.path, s.line"
    ).fetchall()

    counts: dict[str, int] = {}
    grouped: dict[str, list[tuple]] = {}
    for row in rows:
        module = _module_of(row[0])
        grouped.setdefault(module, []).append(row)

    for module, entries in sorted(grouped.items()):
        counts[module] = len(entries)
        lines: list[str] = []
        if lang == "zh":
            lines.append(f"# 明细：{module}（{len(entries)} 个条目）")
            lines.append("")
            lines.append("生成时间：" + datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"))
        else:
            lines.append(f"# Detail: {module} ({len(entries)} entries)")
            lines.append("")
            lines.append("Generated: " + datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"))
        lines.append("")
        for row in entries:
            (fpath, flang, frole, qname, name, kind, sig, params, returns, desc, line, end_line, bases_json) = row
            bases = json.loads(bases_json) if bases_json else []
            bases_str = f" | bases: {', '.join(bases)}" if bases else ""
            lines.append(f"## `{qname}`")
            lines.append("")
            lines.append(f"- file: `{fpath}` (lines {line}-{end_line})")
            lines.append(f"- kind: {kind} | lang: {flang} | role: {frole}{bases_str}")
            lines.append(f"- signature: `{sig}`")
            if params and params != "()":
                lines.append(f"- params: `{params}`")
            if returns:
                lines.append(f"- returns: `{returns}`")
            if desc:
                lines.append(f"- description: {desc}")
            lines.append("")
        (detail_dir / _detail_filename(module)).write_text("\n".join(lines), encoding="utf-8")
    return counts


def render_overview(
    root: Path,
    store: Store,
    result: ScanResult,
    out_path: Path,
    lang: str = "en",
    max_tokens: int | None = None,
) -> None:
    """Render CODEATLAS.md (overview layer).

    EN: frontmatter + 3 Mermaid diagrams + directory tree + one-line-per-file
    table (budget-pruned with omitted-count note) + recent history links.
    ZH: frontmatter + 3 张 Mermaid 图 + 目录树 + 每文件一行简表
    （预算裁剪并标注省略数）+ 最近历史链接。
    """
    diagrams = build_all_diagrams(store)

    file_rows = store.conn.execute(
        "SELECT path, language, role FROM files ORDER BY path"
    ).fetchall()
    symbol_counts: dict[str, int] = {}
    for row in store.conn.execute("SELECT file, COUNT(*) FROM symbols GROUP BY file"):
        symbol_counts[row[0]] = row[1]

    degrees: dict[str, int] = {}
    for src, dst, _sym, count in store.all_refs():
        degrees[dst] = degrees.get(dst, 0) + count

    total_symbols = sum(symbol_counts.values())
    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")

    # ---- budget pruning (only when max_tokens requested) ----
    shown_rows = list(file_rows)
    omitted = 0
    if max_tokens is not None:
        # EN: fixed overhead (frontmatter+diagrams) estimated once; per-file
        # entries ordered by in-degree desc keep the architectural spine.
        # ZH: 固定开销（frontmatter+图）先估一次；每文件条目按入度降序
        # 保留架构主干。
        fixed = 400
        entries = sorted(
            file_rows,
            key=lambda r: (-degrees.get(r[0], 0), r[0]),
        )
        remaining = max_tokens - fixed
        kept: set[str] = set()
        for row in entries:
            line = _file_row(row, symbol_counts, lang)
            cost = estimate_tokens(line)
            if cost <= remaining:
                kept.add(row[0])
                remaining -= cost
        shown_rows = [r for r in file_rows if r[0] in kept]
        omitted = len(file_rows) - len(shown_rows)

    lines: list[str] = []
    lines.append("---")
    lines.append(f"project: {root.name}")
    lines.append(f"generated: {now}")
    lines.append(f"language: {lang}")
    lines.append(f"files: {len(file_rows)}")
    lines.append(f"symbols: {total_symbols}")
    if result.timestamp:
        lines.append(f"last_scan: {result.timestamp}")
    lines.append("---")
    lines.append("")
    # EN: regenerate hint — detail/ is not committed to git (teammates need this).
    # ZH: 再生提示 —— detail/ 不入库（队友 clone 后需要）。
    if lang == "zh":
        lines.append("> 首次使用请运行 `codeatlas scan .` 生成完整明细（.codeatlas/detail/）。")
    else:
        lines.append("> First time here? Run `codeatlas scan .` to generate the full detail (`.codeatlas/detail/`).")
    lines.append("")

    # diagrams
    lines.append("## 架构图 / Diagrams" if lang == "zh" else "## Diagrams")
    lines.append("")
    lines.append("### 目录结构 / Directory Tree" if lang == "zh" else "### Directory Tree")
    lines.append("")
    lines.append("```mermaid")
    lines.append(diagrams["tree"])
    lines.append("```")
    lines.append("")
    lines.append("### 模块依赖 / Module Dependencies" if lang == "zh" else "### Module Dependencies")
    lines.append("")
    lines.append("```mermaid")
    lines.append(diagrams["deps"])
    lines.append("```")
    lines.append("")
    lines.append("### 类继承 / Class Inheritance" if lang == "zh" else "### Class Inheritance")
    lines.append("")
    lines.append("```mermaid")
    lines.append(diagrams["inherit"])
    lines.append("```")
    lines.append("")

    # per-file table
    lines.append("## 文件索引 / Files" if lang == "zh" else "## Files")
    lines.append("")
    if lang == "zh":
        lines.append("| 文件 | 语言 | 角色 | 符号数 | 被引用 |")
        lines.append("|---|---|---|---:|---:|")
    else:
        lines.append("| File | Lang | Role | Symbols | Ref'd |")
        lines.append("|---|---|---|---:|---:|")
    for row in shown_rows:
        lines.append(_file_row(row, symbol_counts, lang, degrees))
    lines.append("")
    if omitted > 0:
        if lang == "zh":
            lines.append(f"> 已省略 {omitted} 个文件（受 --max-tokens 预算限制，详见 `.codeatlas/detail/`）。")
        else:
            lines.append(
                f"> {omitted} file(s) omitted (within --max-tokens budget; see `.codeatlas/detail/`)."
            )
        lines.append("")

    # recent history links
    history_dir = out_path.parent / ".codeatlas" / "history"
    if history_dir.is_dir():
        recent = sorted(history_dir.glob("*.md"), reverse=True)[:5]
        if recent:
            lines.append(
                "## 最近变更记录 / Recent Changes" if lang == "zh" else "## Recent Changes"
            )
            lines.append("")
            for p in recent:
                lines.append(f"- [{p.name}](.codeatlas/history/{p.name})")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def _file_row(row, symbol_counts: dict[str, int], lang: str, degrees: dict[str, int] | None = None) -> str:
    path, language, role = row[0], row[1], row[2]
    n = symbol_counts.get(path, 0)
    refs = degrees.get(path, 0) if degrees else 0
    return f"| `{path}` | {language} | {role} | {n} | {refs} |"
