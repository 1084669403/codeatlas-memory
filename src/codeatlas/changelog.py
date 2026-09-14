"""EN: Human/AI-readable history documents under .codeatlas/history/.
ZH: .codeatlas/history/ 下的人类与 AI 可读历史文档。

EN: One markdown file per update run. Records what changed (symbol-level,
old->new), how much (body line counts via difflib), and includes an
interval warning when the gap since the previous update suggests the
record may not cover all intermediate states.
ZH: 每次 update 生成一个 markdown 文件。记录改了什么（符号级 old->new）、
改了多少（difflib 统计函数体行数），并在距上次更新间隔过长时警示
"本记录可能未覆盖全部中间状态"。
"""

from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path

from .models import ChangeRecord, ChangeType
from .storage import Store

# EN: gap beyond which the history doc carries an "incomplete coverage" warning.
# ZH: 超过该间隔即在校史文档顶部加"可能未覆盖中间状态"警示。
_GAP_WARN_MINUTES = 30

_TITLES = {
    "zh": {
        "added": "新增",
        "removed": "删除",
        "signature_changed": "签名变更",
        "signature_stable": "签名未变（体内可能有修改）",
        "renamed": "疑似重命名",
    },
    "en": {
        "added": "Added",
        "removed": "Removed",
        "signature_changed": "Signature changed",
        "signature_stable": "Signature stable (body may have changed)",
        "renamed": "Suspected rename",
    },
}


def _fmt_ts(ts: str, lang: str) -> str:
    try:
        dt = datetime.fromisoformat(ts).astimezone()
        if lang == "zh":
            return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return ts


def body_change_lines(old_source: str, new_source: str, symbol: str) -> str:
    """Count changed body lines for one symbol via difflib (stdlib only).

    EN: coarse but useful: unified-diff line count between the old and new
    symbol signature lines is not available per-symbol here, so callers pass
    the extracted body text. Kept simple for MVP.
    ZH: 粗略但有用：MVP 阶段按调用方传入的符号体文本做统一 diff 计数。
    """
    if old_source == new_source:
        return "0"
    diff = difflib.unified_diff(
        old_source.splitlines(), new_source.splitlines(), lineterm="", n=0
    )
    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    return f"+{added}/-{removed}"


def _group_by_file(changes: list[ChangeRecord]) -> dict[str, list[ChangeRecord]]:
    grouped: dict[str, list[ChangeRecord]] = {}
    for ch in changes:
        grouped.setdefault(ch.file, []).append(ch)
    return dict(sorted(grouped.items()))


def write_history_doc(
    history_dir: Path,
    store: Store,
    changes: list[ChangeRecord],
    ts: str,
    lang: str = "en",
    files_parsed: int = 0,
    files_scanned: int = 0,
) -> Path:
    """Write one history markdown document; returns the written path.

    EN: filename derives from the update timestamp (local time, minute
    precision). Includes interval warning + recent-history links section.
    ZH: 文件名由 update 时间戳（本地时间，分钟精度）派生。包含间隔警示
    与最近历史链接。
    """
    history_dir.mkdir(parents=True, exist_ok=True)
    local_dt = datetime.now(timezone.utc).astimezone()
    fname = local_dt.strftime("%Y-%m-%d_%H%M.md")
    out_path = history_dir / fname

    t = _TITLES.get(lang, _TITLES["en"])

    lines: list[str] = []
    if lang == "zh":
        lines.append(f"# 变更记录 {local_dt.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append(f"- 更新时间：{_fmt_ts(ts, lang)}")
        lines.append(f"- 扫描文件数：{files_scanned}，重新解析：{files_parsed}")
        lines.append(f"- 符号变更数：{len(changes)}")
        # interval warning
        last_ts = store.last_change_ts()
        if last_ts and last_ts != ts:
            try:
                prev = datetime.fromisoformat(last_ts)
                cur = datetime.fromisoformat(ts)
                gap_min = (cur - prev).total_seconds() / 60
                if gap_min >= _GAP_WARN_MINUTES:
                    lines.append("")
                    lines.append(
                        f"> ⚠️ 距上次记录约 {gap_min:.0f} 分钟：本记录可能未覆盖全部中间状态。"
                    )
            except ValueError:
                pass
        lines.append("")
    else:
        lines.append(f"# Change History {local_dt.strftime('%Y-%m-%d %H:%M')}")
        lines.append("")
        lines.append(f"- Updated at: {_fmt_ts(ts, lang)}")
        lines.append(f"- Files scanned: {files_scanned}, re-parsed: {files_parsed}")
        lines.append(f"- Symbol changes: {len(changes)}")
        last_ts = store.last_change_ts()
        if last_ts and last_ts != ts:
            try:
                prev = datetime.fromisoformat(last_ts)
                cur = datetime.fromisoformat(ts)
                gap_min = (cur - prev).total_seconds() / 60
                if gap_min >= _GAP_WARN_MINUTES:
                    lines.append("")
                    lines.append(
                        f"> ⚠️ About {gap_min:.0f} minutes since the previous record: "
                        "this record may not cover all intermediate states."
                    )
            except ValueError:
                pass
        lines.append("")

    if not changes:
        lines.append(
            "本次运行无符号变更。" if lang == "zh" else "No symbol changes in this run."
        )
    else:
        for file, file_changes in _group_by_file(changes).items():
            lines.append(f"## `{file}`")
            lines.append("")
            for ch in file_changes:
                label = t.get(ch.change_type.value, ch.change_type.value)
                if ch.change_type == ChangeType.SIGNATURE_CHANGED:
                    lines.append(f"- **{label}** `{ch.symbol}`")
                    lines.append(f"  - old: `{ch.old_value}`")
                    lines.append(f"  - new: `{ch.new_value}`")
                elif ch.change_type == ChangeType.RENAMED:
                    lines.append(f"- **{label}** `{ch.old_value}` -> `{ch.new_value}`")
                elif ch.change_type == ChangeType.ADDED:
                    lines.append(f"- **{label}** `{ch.symbol}` — `{ch.new_value}`")
                elif ch.change_type == ChangeType.REMOVED:
                    lines.append(f"- **{label}** `{ch.symbol}` — `{ch.old_value}`")
                else:  # SIGNATURE_STABLE
                    if ch.detail:
                        # EN: body-level edit line counts (+N/-M) — MVP gap 1.
                        # ZH: 体级修改行数（+N/-M）—— MVP 缺口 1。
                        if lang == "zh":
                            lines.append(
                                f"- {label}: `{ch.symbol}`（体内修改 {ch.detail}）"
                            )
                        else:
                            lines.append(
                                f"- {label}: `{ch.symbol}` (body edits {ch.detail})"
                            )
                    else:
                        lines.append(f"- {label}: `{ch.symbol}`")
            lines.append("")

    # EN: links to the most recent history docs (nav aid for rollback review).
    # ZH: 最近历史文档链接（回滚审阅的导航辅助）。
    recent = sorted(history_dir.glob("*.md"), reverse=True)[:6]
    if len(recent) > 1:
        lines.append("---")
        lines.append(
            "### 最近记录 / Recent history" if lang == "zh" else "### Recent history"
        )
        lines.append("")
        for p in recent[:5]:
            lines.append(f"- [{p.name}]({p.name})")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_codeatlas_gitignore(codeatlas_dir: Path) -> None:
    """Create .codeatlas/.gitignore so only history/ is committed.

    EN: state.db and detail/ are regenerable artifacts (not committed);
    history/ is the durable record and IS committed by design.
    ZH: state.db 与 detail/ 是可再生派生物（不入库）；history/ 是持久
    记录，按设计入库。
    """
    codeatlas_dir.mkdir(parents=True, exist_ok=True)
    target = codeatlas_dir / ".gitignore"
    target.write_text("*\n!.gitignore\n!history/\n!history/**\n", encoding="utf-8")
