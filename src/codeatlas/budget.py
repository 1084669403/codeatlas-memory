"""EN: Token budget pure-computation layer (NO project-internal imports).

ZH: Token 预算纯计算层（零项目内 import）。

EN: This module is deliberately dependency-free: memory.py imports budget,
never the reverse (plan P0-1 breaks the budget<->memory cycle). Everything
here is either a pure function or a plain dataclass.
ZH: 本模块刻意保持无依赖：memory.py 单向 import budget（方案 P0-1 打破
budget<->memory 循环）。此处全部为纯函数或纯 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass

# EN: fixed per-page overhead (headers, lists, fences) beyond the rendered text.
# ZH: 每页固定开销（标题、列表、围栏）—— 渲染文本之外的部分。
OVERHEAD = 24

# EN: default budget values; persisted in meta so users can tune them.
# ZH: 默认预算值；持久化在 meta 中供用户调整。
DEFAULT_TOTAL = 8000
DEFAULT_WORKING_SET = 6000
DEFAULT_MAX_PAGES = 50

# EN: eviction weights — recency dominates, locality breaks ties.
# ZH: 淘汰权重 —— recency 主导，locality 决胜。
W_RECENCY = 0.6
W_LOCALITY = 0.4

# EN: prefetch pages get capped recency so real loads evict them first.
# ZH: 预取页 recency 被封顶，真实加载页优先淘汰预取页。
PREFETCH_RECENCY_CAP = 0.7


@dataclass
class Budget:
    """Three independent budget knobs (all persisted in meta).

    EN: working_set = eviction budget for resident pages (evict依据);
    total = token cap on merged render_working_set output (MCP response
    protection). The two apply independently (plan v6).
    ZH: working_set = 驻留页淘汰预算（evict 依据）；total =
    render_working_set 合并输出的 token 上限（MCP 响应保护）。二者独立生效
    （方案 v6）。
    """

    total: int = DEFAULT_TOTAL
    working_set: int = DEFAULT_WORKING_SET
    max_pages: int = DEFAULT_MAX_PAGES


@dataclass
class BudgetReport:
    """Result of a budget check."""

    ok: bool
    over_tokens: int  # EN: tokens above the limit (0 when ok) / ZH: 超额 token 数
    over_pages: int  # EN: pages above max_pages (0 when ok) / ZH: 超限页数
    usage: int  # EN: tokens used / ZH: 已用 token


def estimate_tokens(text: str) -> int:
    """CJK-aware token estimation.

    EN: CJK chars ~1 token each; other chars ~3 chars/token (code density).
    A flat len/4 undercounts Chinese by 3-4x.
    ZH: CJK 字符约 1 token/字；其余约 3 字符/token（代码密度）。
    简单 len/4 会把中文低估 3-4 倍。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf")
    other = len(text) - cjk
    other_tokens = -(-other // 3) if other else 0
    return cjk + other_tokens


def page_cost(rendered: str) -> int:
    """Token cost of one page = rendered text + fixed per-page overhead."""
    return estimate_tokens(rendered) + OVERHEAD


def check(usage: int, pages: int, budget: Budget) -> BudgetReport:
    """Check token usage and page count against the budget."""
    over_tokens = max(0, usage - budget.total)
    over_pages = max(0, pages - budget.max_pages)
    return BudgetReport(
        ok=over_tokens == 0 and over_pages == 0,
        over_tokens=over_tokens,
        over_pages=over_pages,
        usage=usage,
    )


def eviction_score(recency: float, locality: float, origin: str = "load") -> float:
    """Eviction priority score — LOWER means evict FIRST.

    EN: score = 0.6*recency_eff + 0.4*locality; prefetch pages get their
    recency capped at 0.7 so genuinely-loaded pages survive longer (plan v3).
    ZH: score = 0.6*recency_eff + 0.4*locality；预取页 recency 封顶 0.7，
    真实加载页留存更久（方案 v3）。
    """
    recency_eff = min(recency, PREFETCH_RECENCY_CAP) if origin == "prefetch" else recency
    return W_RECENCY * recency_eff + W_LOCALITY * locality


def suggest_evictions(
    entries: list[tuple[str, float, float, bool, str, int]], need_tokens: int
) -> list[str]:
    """Pure eviction planner.

    EN: entries are (page_id, recency, locality, pinned, origin, tokens).
    Returns the page_ids to evict: ascending score (coldest first), pinned
    pages skipped, until the evicted pages' combined tokens cover
    need_tokens. Over-selection is fine (caller re-checks).
    ZH: entries 为 (page_id, recency, locality, pinned, origin, tokens)。
    按分数升序（最冷先淘汰）返回应淘汰的 page_id，跳过 pinned，直到被淘汰
    页的 token 合计覆盖 need_tokens。允许多选（调用方会复核）。
    """
    candidates = [e for e in entries if not e[3]]
    candidates.sort(key=lambda e: eviction_score(e[1], e[2], e[4]))
    picked: list[str] = []
    covered = 0
    for page_id, _rec, _loc, _pinned, _origin, tokens in candidates:
        if covered >= need_tokens:
            break
        picked.append(page_id)
        covered += tokens
    return picked
