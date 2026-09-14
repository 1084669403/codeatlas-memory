"""EN: Core data models shared across the CodeAtlas pipeline.
ZH: CodeAtlas 管线共享的核心数据模型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SymbolKind(str, Enum):
    """Kind of a code symbol extracted from source."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"


class ChangeType(str, Enum):
    """Change classification for a symbol between two scans.

    EN: "signature_stable" means name+signature+params+returns are unchanged;
    it does NOT claim the change is formatting-only (body logic may differ).
    ZH: "signature_stable" 表示名称/签名/参数/返回值未变；
    不代表"仅格式调整"（函数体逻辑可能已变化）。
    """

    ADDED = "added"
    REMOVED = "removed"
    SIGNATURE_CHANGED = "signature_changed"
    SIGNATURE_STABLE = "signature_stable"
    RENAMED = "renamed"


class Role(str, Enum):
    """Inferred architectural role of a file or symbol (heuristic)."""

    CONTROLLER = "controller"
    SERVICE = "service"
    MODEL = "model"
    UTIL = "util"
    TEST = "test"
    ENTRY = "entry"
    MODULE = "module"
    COMPONENT = "component"


@dataclass
class Import:
    """A single import/require statement, used for the dependency graph."""

    source: str  # EN: raw module path, e.g. "./utils" or "os.path" / ZH: 原始模块路径
    names: list[str] = field(default_factory=list)  # imported symbol names


@dataclass
class Symbol:
    """A code symbol (function / class / method / interface / type alias)."""

    qualified_name: str  # EN: module.Class.method (py) / path::Class.method (js/ts) / ZH: 限定名
    name: str
    kind: SymbolKind
    signature: str
    params: str
    returns: str
    description: str = ""
    role: str = Role.MODULE.value
    line: int = 0  # 1-based start line
    end_line: int = 0
    language: str = ""
    docstring: str = ""  # EN: raw docstring/JSDoc first paragraph / ZH: 原始文档字符串
    bases: list[str] = field(default_factory=list)  # EN: class bases/implements / ZH: 基类


@dataclass
class FileRecord:
    """Per-file state persisted in SQLite (current state, not history)."""

    path: str  # EN: repo-relative POSIX path / ZH: 仓库相对 POSIX 路径
    language: str  # python / javascript / typescript
    hash: str  # sha256 of content
    mtime: float
    size: int
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    role: str = Role.MODULE.value


@dataclass
class ChangeRecord:
    """One symbol-level change, persisted append-only in the changes table.

    EN: old_value/new_value hold before/after (signature etc.) so a human or
    AI can roll back by reading the old value — this is the core of
    record-based rollback.
    ZH: old_value/new_value 保存前后对照（签名等），人或 AI 可按旧值
    回滚 —— 这是记录型回滚的核心。
    """

    ts: str  # ISO timestamp of the update run
    file: str
    symbol: str  # qualified name
    change_type: ChangeType
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    detail: str = ""  # EN: extra human-readable detail (e.g. body diff lines) / ZH: 附加说明


@dataclass
class ScanResult:
    """Aggregate result of a scan or incremental update run."""

    root: str
    files_scanned: int = 0
    files_parsed: int = 0  # EN: actually re-parsed (incremental: only changed) / ZH: 实际重新解析数
    files_skipped: int = 0
    symbols_found: int = 0
    changes: list[ChangeRecord] = field(default_factory=list)
    lang: str = "en"
    timestamp: str = ""
