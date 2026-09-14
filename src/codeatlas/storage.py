"""EN: SQLite-backed state store: files, symbols, refs edge table, changes, meta.

ZH: SQLite 状态存储：files / symbols / refs 边表 / changes / meta。

EN: Design notes
- WAL journal mode: concurrent readers (future MCP server) won't block writers.
- `symbols` holds the CURRENT state (rewritten per file on update);
  `changes` is append-only HISTORY — the two-table split is what makes the
  lightweight `history` command possible without supersedes columns.
- All paths are repo-relative POSIX strings for cross-platform key stability.
ZH: 设计要点
- WAL 日志模式：并发读（未来 MCP server）不会阻塞写。
- `symbols` 存当前态（update 时按文件重写）；`changes` 只追加历史 ——
  双表分离让轻量 history 命令无需 supersedes 列即可实现。
- 所有路径为仓库相对 POSIX 字符串，保证跨平台键一致。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import ChangeRecord, ChangeType, FileRecord, Symbol

_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    hash TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    role TEXT NOT NULL,
    parsed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS symbols (
    file TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    signature TEXT NOT NULL,
    params TEXT NOT NULL,
    returns TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL,
    line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    language TEXT NOT NULL,
    bases TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (file, qualified_name),
    FOREIGN KEY (file) REFERENCES files(path) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS refs (
    src_file TEXT NOT NULL,
    dst_file TEXT NOT NULL,
    symbol TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (src_file, dst_file, symbol)
);

CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    file TEXT NOT NULL,
    symbol TEXT NOT NULL,
    change_type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    detail TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_changes_symbol ON changes(symbol);
CREATE INDEX IF NOT EXISTS idx_changes_ts ON changes(ts);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with WAL + FK enforcement applied."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class Store:
    """Persistent state for one scanned project (one state.db per project)."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = _connect(db_path)
        self.conn.executescript(_SCHEMA)
        self.conn.commit()
        self._fts_enabled = self._init_fts()

    # ------------------------------------------------------------------ meta

    def _init_fts(self) -> bool:
        """Create the FTS5 trigram index if SQLite supports it.

        EN: trigram tokenizer needs SQLite >= 3.34 and FTS5 compiled in; on
        failure we degrade gracefully (query falls back to LIKE).
        ZH: trigram 分词器需要 SQLite >= 3.34 且编译了 FTS5；不支持时
        优雅降级（query 回退 LIKE）。
        """
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5("
                "qualified_name, name, signature, description, file, "
                "content='symbols', content_rowid='rowid', tokenize='trigram')"
            )
            self.conn.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
                    INSERT INTO symbols_fts(rowid, qualified_name, name, signature, description, file)
                    VALUES (new.rowid, new.qualified_name, new.name, new.signature, new.description, new.file);
                END;
                CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
                    INSERT INTO symbols_fts(symbols_fts, rowid, qualified_name, name, signature, description, file)
                    VALUES ('delete', old.rowid, old.qualified_name, old.name, old.signature, old.description, old.file);
                END;
                CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
                    INSERT INTO symbols_fts(symbols_fts, rowid, qualified_name, name, signature, description, file)
                    VALUES ('delete', old.rowid, old.qualified_name, old.name, old.signature, old.description, old.file);
                    INSERT INTO symbols_fts(rowid, qualified_name, name, signature, description, file)
                    VALUES (new.rowid, new.qualified_name, new.name, new.signature, new.description, new.file);
                END;
                """
            )
            self.conn.commit()
            return True
        except sqlite3.OperationalError:
            self.conn.rollback()
            return False

    @property
    def fts_enabled(self) -> bool:
        """Whether the FTS5 trigram index is available (False -> LIKE fallback)."""
        return self._fts_enabled

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    # ----------------------------------------------------------------- files

    def upsert_file(self, record: FileRecord, parsed_at: str) -> None:
        """Insert/replace one file with its symbols (current-state semantics)."""
        cur = self.conn.execute(
            "INSERT INTO files(path, language, hash, mtime, size, role, parsed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET language=excluded.language, hash=excluded.hash, "
            "mtime=excluded.mtime, size=excluded.size, role=excluded.role, parsed_at=excluded.parsed_at",
            (record.path, record.language, record.hash, record.mtime, record.size, record.role, parsed_at),
        )
        file_rowid = cur.lastrowid
        self.conn.execute("DELETE FROM symbols WHERE file = ?", (record.path,))
        for sym in record.symbols:
            self.conn.execute(
                "INSERT INTO symbols(file, qualified_name, name, kind, signature, params, returns, "
                "description, role, line, end_line, language, bases) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.path,
                    sym.qualified_name,
                    sym.name,
                    sym.kind.value,
                    sym.signature,
                    sym.params,
                    sym.returns,
                    sym.description,
                    sym.role,
                    sym.line,
                    sym.end_line,
                    sym.language,
                    json.dumps(sym.bases, ensure_ascii=False),
                ),
            )
        self.conn.commit()

    def get_file_hash(self, path: str) -> str | None:
        row = self.conn.execute("SELECT hash FROM files WHERE path = ?", (path,)).fetchone()
        return row[0] if row else None

    def get_all_file_hashes(self) -> dict[str, str]:
        return {row[0]: row[1] for row in self.conn.execute("SELECT path, hash FROM files")}

    def delete_file(self, path: str) -> None:
        """Remove a file and its symbols (refs edges are handled by indexer)."""
        self.conn.execute("DELETE FROM symbols WHERE file = ?", (path,))
        self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self.conn.commit()

    def known_paths(self) -> set[str]:
        return {row[0] for row in self.conn.execute("SELECT path FROM files")}

    # --------------------------------------------------------------- symbols

    def all_symbols(self) -> list[tuple]:
        """Return (file, qualified_name, name, kind, signature, params, returns, role) tuples."""
        return list(
            self.conn.execute(
                "SELECT file, qualified_name, name, kind, signature, params, returns, role FROM symbols"
            )
        )

    def symbols_for_file(self, path: str) -> list[tuple]:
        return list(
            self.conn.execute(
                "SELECT file, qualified_name, name, kind, signature, params, returns, role "
                "FROM symbols WHERE file = ?",
                (path,),
            )
        )

    # ------------------------------------------------------------------ refs

    def replace_refs_for_file(self, src_file: str, edges: list[tuple[str, str, int]]) -> None:
        """Replace all outgoing ref edges of one file (src -> dst with count)."""
        self.conn.execute("DELETE FROM refs WHERE src_file = ?", (src_file,))
        self.conn.executemany(
            "INSERT OR REPLACE INTO refs(src_file, dst_file, symbol, count) VALUES (?, ?, ?, ?)",
            edges,
        )
        self.conn.commit()

    def all_refs(self) -> list[tuple[str, str, str, int]]:
        return list(self.conn.execute("SELECT src_file, dst_file, symbol, count FROM refs"))

    # --------------------------------------------------------------- changes

    def append_changes(self, records: list[ChangeRecord]) -> None:
        """Append change records (never updated or deleted — history is immutable)."""
        self.conn.executemany(
            "INSERT INTO changes(ts, file, symbol, change_type, old_value, new_value, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (r.ts, r.file, r.symbol, r.change_type.value, r.old_value, r.new_value, r.detail)
                for r in records
            ],
        )
        self.conn.commit()

    def changes_for_symbol(self, symbol: str, limit: int = 200) -> list[ChangeRecord]:
        """All historical changes for one qualified symbol name, oldest first."""
        rows = self.conn.execute(
            "SELECT ts, file, symbol, change_type, old_value, new_value, detail "
            "FROM changes WHERE symbol = ? ORDER BY ts ASC, id ASC LIMIT ?",
            (symbol, limit),
        ).fetchall()
        return [
            ChangeRecord(
                ts=r[0],
                file=r[1],
                symbol=r[2],
                change_type=ChangeType(r[3]),
                old_value=r[4],
                new_value=r[5],
                detail=r[6],
            )
            for r in rows
        ]

    def changes_by_symbol_name(self, name: str) -> dict[str, int]:
        """Count changes grouped by qualified name for a bare symbol name."""
        return {
            row[0]: row[1]
            for row in self.conn.execute(
                "SELECT symbol, COUNT(*) FROM changes WHERE symbol LIKE ? GROUP BY symbol",
                (f"%.{name}",),
            )
        }

    def last_change_ts(self) -> str | None:
        row = self.conn.execute("SELECT MAX(ts) FROM changes").fetchone()
        return row[0] if row and row[0] else None

    def close(self) -> None:
        self.conn.close()
