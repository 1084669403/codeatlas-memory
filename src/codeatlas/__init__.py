"""CodeAtlas: persistent code index & architecture memory for AI-assisted development.

EN: CodeAtlas scans a codebase, extracts symbols (functions, classes, methods)
via tree-sitter, and maintains a layered Markdown index plus a SQLite state
store. It is designed to give AI coding agents a compact, queryable memory of
a project's structure so they never need to re-read the whole codebase.

ZH: CodeAtlas 扫描代码库，通过 tree-sitter 提取符号（函数、类、方法），
维护分层 Markdown 索引与 SQLite 状态存储。它为 AI 编程工具提供紧凑、
可查询的项目结构记忆，避免每次重读全量代码。
"""

from __future__ import annotations

__version__ = "0.1.0"
