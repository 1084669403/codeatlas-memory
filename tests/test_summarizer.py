"""EN: Tests for rule-based summarizer and role inference.
ZH: 规则摘要与角色推断测试。
"""

from __future__ import annotations

from codeatlas.models import Symbol, SymbolKind
from codeatlas.summarizer import RuleSummarizer, infer_role


def test_role_controllers() -> None:
    assert infer_role("api/controllers/users.py") == "controller"


def test_role_service_by_name() -> None:
    assert infer_role("src/order_service.py") == "service"


def test_role_model_and_test() -> None:
    assert infer_role("db/models/user.py") == "model"
    assert infer_role("tests/test_parser.py") == "test"


def test_role_entry_and_default() -> None:
    assert infer_role("src/main.py") == "entry"
    assert infer_role("src/core/engine.py") == "module"


def test_docstring_wins_over_template() -> None:
    s = Symbol(
        qualified_name="m.f",
        name="f",
        kind=SymbolKind.FUNCTION,
        signature="def f()",
        params="()",
        returns="",
        docstring="Does the real thing.",
    )
    out = RuleSummarizer().describe_symbol(s, "en")
    assert out == "Does the real thing."


def test_template_zh_and_en() -> None:
    s = Symbol(
        qualified_name="m.f",
        name="f",
        kind=SymbolKind.FUNCTION,
        signature="def f()",
        params="()",
        returns="int",
        line=7,
    )
    zh = RuleSummarizer().describe_symbol(s, "zh")
    en = RuleSummarizer().describe_symbol(s, "en")
    assert "函数" in zh and "第 7 行" in zh and "int" in zh
    assert "Function" in en and "line 7" in en and "int" in en
