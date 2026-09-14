"""EN: Rule-based bilingual (zh/en) summaries + architectural role inference.
ZH: 基于规则的中英双语摘要 + 架构角色推断。

EN: This module is intentionally LLM-free. The Summarizer protocol exists so a
future LLM-backed implementation can be swapped in without touching callers.
ZH: 本模块刻意不依赖 LLM。预留 Summarizer 协议以便未来替换为 LLM 实现，
调用方无需改动。
"""

from __future__ import annotations

from typing import Protocol

from .models import FileRecord, Role, Symbol

# EN: path/name heuristics for architectural role inference (checked in order).
# ZH: 架构角色推断的路径/命名启发式（按顺序匹配）。
_ROLE_RULES: list[tuple[str, Role]] = [
    ("controllers/", Role.CONTROLLER),
    ("controller_", Role.CONTROLLER),
    ("views.py", Role.CONTROLLER),  # django-style views are controllers
    ("services/", Role.SERVICE),
    ("service_", Role.SERVICE),
    ("_service", Role.SERVICE),
    ("models/", Role.MODEL),
    ("model_", Role.MODEL),
    ("entities/", Role.MODEL),
    ("schemas/", Role.MODEL),
    ("utils/", Role.UTIL),
    ("util_", Role.UTIL),
    ("_utils", Role.UTIL),
    ("helpers/", Role.UTIL),
    ("tests/", Role.TEST),
    ("test_", Role.TEST),
    ("_test", Role.TEST),
    ("components/", Role.COMPONENT),
    ("pages/", Role.COMPONENT),
    ("main.py", Role.ENTRY),
    ("main.ts", Role.ENTRY),
    ("main.js", Role.ENTRY),
    ("index.ts", Role.ENTRY),
    ("index.js", Role.ENTRY),
    ("app.py", Role.ENTRY),
    ("app.ts", Role.ENTRY),
    ("app.js", Role.ENTRY),
    ("cli.py", Role.ENTRY),
    ("__main__.py", Role.ENTRY),
]


def infer_role(rel_posix: str) -> str:
    """Infer the architectural role of a file from its path/name.

    EN: Pure function; first matching rule wins; default is 'module'.
    ZH: 纯函数；首个命中的规则生效；默认 'module'。
    """
    normalized = rel_posix.lower().replace("\\", "/")
    for needle, role in _ROLE_RULES:
        if needle in normalized:
            return role.value
    return Role.MODULE.value


class Summarizer(Protocol):
    """Protocol so an LLM-backed summarizer can replace the rule engine later."""

    def describe_symbol(self, symbol: Symbol, lang: str) -> str: ...

    def describe_file(self, record: FileRecord, lang: str) -> str: ...


def _first_sentence(text: str) -> str:
    """Take the first line/sentence of a docstring, trimmed."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _kind_label(kind: str, lang: str) -> str:
    labels = {
        "zh": {
            "function": "函数",
            "class": "类",
            "method": "方法",
            "interface": "接口",
            "type_alias": "类型别名",
        },
        "en": {
            "function": "Function",
            "class": "Class",
            "method": "Method",
            "interface": "Interface",
            "type_alias": "Type alias",
        },
    }
    return labels.get(lang, labels["en"]).get(kind, kind)


class RuleSummarizer:
    """Deterministic template-based summarizer (MVP default)."""

    def describe_symbol(self, symbol: Symbol, lang: str) -> str:
        """Build a one-line description for a symbol.

        EN: docstring first line wins; otherwise a bilingual template with
        name/kind/params/returns so the index stays useful without docs.
        ZH: 优先 docstring 首行；否则用双语模板（名称/种类/参数/返回值），
        保证无文档代码也有可用摘要。
        """
        doc = _first_sentence(symbol.docstring) if symbol.docstring else ""
        if doc:
            return doc

        kind = _kind_label(symbol.kind.value, lang)
        ret = symbol.returns.strip()
        if lang == "zh":
            ret_part = f"，返回 {ret}" if ret else ""
            return f"{kind} {symbol.name}，定义于第 {symbol.line} 行{ret_part}。"
        ret_part = f", returns {ret}" if ret else ""
        return f"{kind} {symbol.name} defined at line {symbol.line}{ret_part}."

    def describe_file(self, record: FileRecord, lang: str) -> str:
        """Build a one-line summary for a file (counts by kind)."""
        funcs = sum(1 for s in record.symbols if s.kind.value in ("function", "method"))
        classes = sum(1 for s in record.symbols if s.kind.value in ("class", "interface"))
        role = record.role
        if lang == "zh":
            return f"{funcs} 个函数/方法，{classes} 个类/接口，架构角色：{role}。"
        return f"{funcs} function(s)/method(s), {classes} class(es)/interface(s), role: {role}."


def enrich(record: FileRecord, summarizer: RuleSummarizer, lang: str) -> FileRecord:
    """Fill role + per-symbol descriptions on a parsed FileRecord (in place)."""
    record.role = infer_role(record.path)
    for symbol in record.symbols:
        symbol.role = record.role
        symbol.description = summarizer.describe_symbol(symbol, lang)
    return record
