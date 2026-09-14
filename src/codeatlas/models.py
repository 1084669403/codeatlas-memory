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
    # EN: normalized function body (CRLF->LF; 64KB truncation) — the first link
    # of the body-level diff chain (parser -> storage -> indexer diff).
    # ZH: 归一化函数体（CRLF->LF；64KB 截断）—— 体级 diff 链路第一环
    # （parser -> storage -> indexer diff）。file 级页不用。
    body: str = ""


# EN: body extraction cap — huge bodies are low-value for diffing/rendering.
# ZH: 函数体提取上限 —— 超大体对 diff/渲染价值低。
BODY_MAX_BYTES = 64 * 1024


@dataclass
class CallEdge:
    """A raw call edge produced by parser stage A (persisted to raw_calls).

    EN: callee_raw is the call text as written (e.g. "self.complete", "helper");
    resolution to a qualified callee happens later in callgraph stage B.
    ZH: callee_raw 是调用点的原始文本（如 "self.complete"、"helper"）；
    解析为限定名发生在 callgraph 阶段 B。
    """

    src_qname: str  # EN: caller qualified name / ZH: 调用方限定名
    callee_raw: str  # EN: call text as written / ZH: 调用原文
    line: int  # 1-based


@dataclass
class Page:
    """A virtual-memory page: one loadable unit of code context.

    EN: page_id is a qualified name (function granularity) or a repo path
    (file granularity); version is the file hash at load time and is the
    staleness criterion.
    ZH: page_id 是限定名（function 粒度）或仓库路径（file 粒度）；
    version 是加载时的文件 hash，作为失效判据。
    """

    page_id: str
    granularity: str  # function | file  (module-level pages are out of scope)
    file: str
    line: int
    end_line: int
    signature: str
    summary: str
    role: str
    language: str
    version: str  # file hash at load time
    callers: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)
    source: str = ""  # EN: optional body excerpt (--source) / ZH: 可选函数体摘录（--source）


@dataclass
class WorkingSetEntry:
    """One resident page in the working set (virtual-memory page table row).

    EN: origin records how the page entered the set ("load" | "prefetch");
    prefetch pages get a recency discount during eviction. Locality is NOT
    stored — it is computed against meta['last_anchor'] at eviction time so
    that a single global anchor serves all processes.
    ZH: origin 记录页面进入方式（"load" | "prefetch"）；预取页在淘汰时打
    recency 折扣。locality 不落库 —— 淘汰时对 meta['last_anchor'] 现算，
    全局唯一锚点，消除多进程下的排序歧义。
    """

    page_id: str
    loaded_at: str
    last_access_at: str
    pinned: bool = False
    tokens: int = 0
    origin: str = "load"  # load | prefetch


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
    # EN: raw call edges from inside symbol bodies (stage-A input; module-level
    # calls outside functions are NOT collected — plan P2-11).
    # ZH: 符号体内采集的原始调用边（阶段 A 原料；函数体外的模块级调用
    # 不采集 —— 方案 P2-11）。
    calls: list[CallEdge] = field(default_factory=list)


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
