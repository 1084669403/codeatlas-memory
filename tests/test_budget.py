"""EN: Budget pure-computation layer tests (incl. one-way dependency check).
ZH: 预算纯计算层测试（含单向依赖检查）。
"""

from __future__ import annotations

import subprocess
import sys

from codeatlas import budget
from codeatlas.budget import (
    OVERHEAD,
    PREFETCH_RECENCY_CAP,
    Budget,
    estimate_tokens,
    check,
    eviction_score,
    page_cost,
    suggest_evictions,
)


def test_cjk_vs_ascii_cost() -> None:
    zh = estimate_tokens("你好世界" * 10)  # 40 CJK chars
    assert zh == 40  # ~1 token per CJK char
    ascii_text = "a" * 33
    assert 10 <= estimate_tokens(ascii_text) <= 12  # ~3 chars/token


def test_overhead_and_page_cost() -> None:
    assert page_cost("") == OVERHEAD
    assert page_cost("hello") == estimate_tokens("hello") + OVERHEAD


def test_check_over_budget() -> None:
    b = Budget(total=100, working_set=80, max_pages=2)
    ok = check(50, 1, b)
    assert ok.ok and ok.over_tokens == 0 and ok.over_pages == 0
    over = check(120, 5, b)
    assert not over.ok
    assert over.over_tokens == 20
    assert over.over_pages == 3


def test_prefetch_recency_discount() -> None:
    # same recency/locality: prefetch page scores lower -> evicted first
    load_score = eviction_score(1.0, 0.5, "load")
    prefetch_score = eviction_score(1.0, 0.5, "prefetch")
    assert prefetch_score < load_score
    # cap applied only to prefetch
    assert eviction_score(1.0, 0.0, "prefetch") == (
        budget.W_RECENCY * PREFETCH_RECENCY_CAP + budget.W_LOCALITY * 0.0
    )


def test_suggest_evictions_skips_pinned_and_covers_need() -> None:
    entries = [
        ("hot.load", 0.9, 0.9, False, "load", 100),
        ("cold.prefetch", 0.2, 0.2, False, "prefetch", 150),
        ("pinned.page", 0.1, 0.1, True, "load", 500),
        ("mid.load", 0.5, 0.5, False, "load", 100),
    ]
    picked = suggest_evictions(entries, 150)
    assert picked[0] == "cold.prefetch"  # lowest score first
    assert "pinned.page" not in picked
    assert "hot.load" not in picked  # 250 tokens covered before reaching it


def test_budget_defaults() -> None:
    b = Budget()
    assert b.total == 8000 and b.working_set == 6000 and b.max_pages == 50


def test_budget_does_not_import_memory() -> None:
    """P0-1 one-way dependency: importing budget must not pull in memory."""
    code = (
        "import sys; import codeatlas.budget; "
        "assert not any(m == 'codeatlas.memory' or m.startswith('codeatlas.memory.') "
        "for m in sys.modules), 'budget must not import memory'; print('OK')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "OK" in r.stdout
