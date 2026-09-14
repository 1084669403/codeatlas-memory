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

from .models import (
    BODY_MAX_BYTES,
    CallEdge,
    ChangeRecord,
    ChangeType,
    FileRecord,
    Symbol,
    WorkingSetEntry,
)

_SCHEMA_VERSION = 2

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

CREATE TABLE IF NOT EXISTS raw_calls (
    file TEXT NOT NULL,
    src_qname TEXT NOT NULL,
    callee_raw TEXT NOT NULL,
    line INTEGER NOT NULL,
    PRIMARY KEY (file, src_qname, callee_raw, line)
);

CREATE TABLE IF NOT EXISTS call_edges (
    src_qname TEXT NOT NULL,
    dst_qname TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (src_qname, dst_qname)
);

CREATE TABLE IF NOT EXISTS pages (
    page_id TEXT PRIMARY KEY,
    file TEXT NOT NULL,
    version TEXT NOT NULL,
    granularity TEXT NOT NULL,
    loaded_at TEXT NOT NULL,
    load_count INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS working_set (
    page_id TEXT PRIMARY KEY,
    loaded_at TEXT NOT NULL,
    last_access_at TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    origin TEXT NOT NULL DEFAULT 'load'
);

CREATE INDEX IF NOT EXISTS idx_changes_symbol ON changes(symbol);
CREATE INDEX IF NOT EXISTS idx_changes_ts ON changes(ts);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_raw_calls_src ON raw_calls(src_qname);
CREATE INDEX IF NOT EXISTS idx_call_edges_src ON call_edges(src_qname);
CREATE INDEX IF NOT EXISTS idx_call_edges_dst ON call_edges(dst_qname);
"""

# EN: Incremental migration statements for databases created by schema v1.
# ZH: 针对 schema v1 创建的库的增量迁移语句。
_MIGRATIONS = (
    ("body", "ALTER TABLE symbols ADD COLUMN body TEXT NOT NULL DEFAULT ''"),
)


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with WAL + FK enforcement applied."""
    # EN: tests and API users may pass a nested path that doesn't exist yet.
    # ZH: 测试与 API 调用方可能传入尚不存在的嵌套路径。
    db_path.parent.mkdir(parents=True, exist_ok=True)
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
        self._migrate()
        self.conn.commit()
        self._fts_enabled = self._init_fts()

    def _migrate(self) -> None:
        """Apply incremental migrations (v1 -> v2 adds symbols.body).

        EN: checked per-column so opening an old state.db upgrades in place
        without touching any other data (plan P1-1 migration baseline).
        ZH: 逐列检查，老 state.db 原地升级，不影响其他数据
        （方案 P1-1 迁移基线）。
        """
        existing = {
            row[1] for row in self.conn.execute("PRAGMA table_info(symbols)")
        }
        for column, ddl in _MIGRATIONS:
            if column not in existing:
                self.conn.execute(ddl)

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
            # EN: enforce the 64KB body cap at write time (belt-and-braces:
            # parser already truncates).
            # ZH: 写入时兜底执行 64KB 体上限（双保险：parser 已截断）。
            body = sym.body
            if len(body.encode("utf-8", "replace")) > BODY_MAX_BYTES:
                body = body.encode("utf-8")[:BODY_MAX_BYTES].decode("utf-8", "ignore")
            self.conn.execute(
                "INSERT INTO symbols(file, qualified_name, name, kind, signature, params, returns, "
                "description, role, line, end_line, language, bases, body) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    body,
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

    # ------------------------------------------------- symbols (body-aware)

    def symbols_for_file_full(self, path: str) -> list[tuple]:
        """Return full symbol rows incl. body for diffing.

        EN: row shape: (file, qualified_name, name, kind, signature, params,
        returns, role, line, end_line, language, bases_json, body).
        ZH: 行结构：(file, qualified_name, name, kind, signature, params,
        returns, role, line, end_line, language, bases_json, body)。
        """
        return list(
            self.conn.execute(
                "SELECT file, qualified_name, name, kind, signature, params, returns, role, "
                "line, end_line, language, bases, body FROM symbols WHERE file = ?",
                (path,),
            )
        )

    def symbol_row(self, qname: str) -> tuple | None:
        """One full symbol row by qualified name (None when absent)."""
        return self.conn.execute(
            "SELECT file, qualified_name, name, kind, signature, params, returns, role, "
            "line, end_line, language, bases, body FROM symbols WHERE qualified_name = ?",
            (qname,),
        ).fetchone()

    def symbols_by_name(self, name: str) -> list[tuple]:
        """All full symbol rows whose bare name matches exactly."""
        return list(
            self.conn.execute(
                "SELECT file, qualified_name, name, kind, signature, params, returns, role, "
                "line, end_line, language, bases, body FROM symbols WHERE name = ? ORDER BY qualified_name",
                (name,),
            )
        )

    # ------------------------------------------------------------ raw_calls

    def replace_raw_calls(self, file: str, edges: list[CallEdge]) -> None:
        """Replace all raw call edges of one file (incremental stage-A input).

        EN: DELETE-then-insert keeps unchanged files' raw calls intact while
        giving changed files a clean replacement (plan P0-2).
        ZH: 先删后插保证未变更文件的 raw calls 不丢，变更文件获得干净替换
        （方案 P0-2）。
        """
        self.conn.execute("DELETE FROM raw_calls WHERE file = ?", (file,))
        self.conn.executemany(
            "INSERT OR IGNORE INTO raw_calls(file, src_qname, callee_raw, line) VALUES (?, ?, ?, ?)",
            [(file, e.src_qname, e.callee_raw, e.line) for e in edges],
        )
        self.conn.commit()

    def all_raw_calls(self) -> list[tuple[str, str, str, int]]:
        """Return (file, src_qname, callee_raw, line) for every raw call."""
        return list(
            self.conn.execute("SELECT file, src_qname, callee_raw, line FROM raw_calls")
        )

    def raw_call_files(self) -> set[str]:
        """Files that have at least one raw call row (orphan detection)."""
        return {row[0] for row in self.conn.execute("SELECT DISTINCT file FROM raw_calls")}

    def delete_raw_calls(self, file: str) -> None:
        """Drop raw calls for a deleted file (prevents orphan accumulation)."""
        self.conn.execute("DELETE FROM raw_calls WHERE file = ?", (file,))
        self.conn.commit()

    # ----------------------------------------------------------- call_edges

    def replace_call_edges(self, edges: list[tuple[str, str, int]]) -> None:
        """Atomically rewrite the whole call_edges table (stage B output)."""
        self.conn.execute("DELETE FROM call_edges")
        self.conn.executemany(
            "INSERT OR REPLACE INTO call_edges(src_qname, dst_qname, count) VALUES (?, ?, ?)",
            edges,
        )
        self.conn.commit()

    def all_call_edges(self) -> list[tuple[str, str, int]]:
        return list(self.conn.execute("SELECT src_qname, dst_qname, count FROM call_edges"))

    def callers_of(self, qname: str) -> list[str]:
        """Qualified names of symbols that call qname (dedup, sorted)."""
        rows = self.conn.execute(
            "SELECT DISTINCT src_qname FROM call_edges WHERE dst_qname = ? ORDER BY src_qname",
            (qname,),
        ).fetchall()
        return [r[0] for r in rows]

    def callees_of(self, qname: str) -> list[str]:
        """Qualified names of symbols that qname calls (dedup, sorted)."""
        rows = self.conn.execute(
            "SELECT DISTINCT dst_qname FROM call_edges WHERE src_qname = ? ORDER BY dst_qname",
            (qname,),
        ).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------- pages/working set

    def upsert_page(self, page_id: str, file: str, version: str, granularity: str, loaded_at: str) -> None:
        """Record a page load in the page table (load_count increments).

        EN: pages is the "ever loaded" table — stats survive eviction; only
        working_set rows are removed by eviction.
        ZH: pages 是"曾加载过"的页表 —— 统计在淘汰后保留；淘汰只删
        working_set 行。
        """
        self.conn.execute(
            "INSERT INTO pages(page_id, file, version, granularity, loaded_at, load_count) "
            "VALUES (?, ?, ?, ?, ?, 1) "
            "ON CONFLICT(page_id) DO UPDATE SET version = excluded.version, "
            "loaded_at = excluded.loaded_at, load_count = load_count + 1",
            (page_id, file, version, granularity, loaded_at),
        )
        self.conn.commit()

    def get_page(self, page_id: str) -> tuple | None:
        row = self.conn.execute(
            "SELECT page_id, file, version, granularity, loaded_at, load_count FROM pages WHERE page_id = ?",
            (page_id,),
        ).fetchone()
        return row

    def upsert_page_version(self, page_id: str, version: str) -> None:
        """Update a page's recorded version without bumping load_count."""
        self.conn.execute(
            "UPDATE pages SET version = ? WHERE page_id = ?", (version, page_id)
        )
        self.conn.commit()

    def all_pages(self) -> list[tuple]:
        return list(
            self.conn.execute(
                "SELECT page_id, file, version, granularity, loaded_at, load_count FROM pages"
            )
        )

    def upsert_working_set(self, entry: WorkingSetEntry) -> None:
        self.conn.execute(
            "INSERT INTO working_set(page_id, loaded_at, last_access_at, pinned, tokens, origin) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(page_id) DO UPDATE SET last_access_at = excluded.last_access_at, "
            "tokens = excluded.tokens, pinned = excluded.pinned, origin = excluded.origin",
            (entry.page_id, entry.loaded_at, entry.last_access_at, int(entry.pinned), entry.tokens, entry.origin),
        )
        self.conn.commit()

    def get_working_set_entry(self, page_id: str) -> WorkingSetEntry | None:
        row = self.conn.execute(
            "SELECT page_id, loaded_at, last_access_at, pinned, tokens, origin "
            "FROM working_set WHERE page_id = ?",
            (page_id,),
        ).fetchone()
        if row is None:
            return None
        return WorkingSetEntry(
            page_id=row[0],
            loaded_at=row[1],
            last_access_at=row[2],
            pinned=bool(row[3]),
            tokens=row[4],
            origin=row[5],
        )

    def working_set_entries(self) -> list[WorkingSetEntry]:
        rows = self.conn.execute(
            "SELECT page_id, loaded_at, last_access_at, pinned, tokens, origin FROM working_set"
        ).fetchall()
        return [
            WorkingSetEntry(
                page_id=r[0],
                loaded_at=r[1],
                last_access_at=r[2],
                pinned=bool(r[3]),
                tokens=r[4],
                origin=r[5],
            )
            for r in rows
        ]

    def delete_working_set_entry(self, page_id: str) -> None:
        self.conn.execute("DELETE FROM working_set WHERE page_id = ?", (page_id,))
        self.conn.commit()

    def clear_working_set(self) -> None:
        """Remove all working-set rows (used after a full scan rebuild)."""
        self.conn.execute("DELETE FROM working_set")
        self.conn.commit()

    # ------------------------------------------------------- index bookkeeping

    def index_version(self) -> int:
        """Monotonic index version (incremented after every update)."""
        raw = self.get_meta("index_version")
        return int(raw) if raw else 0

    def bump_index_version(self) -> int:
        nxt = self.index_version() + 1
        self.set_meta("index_version", str(nxt))
        return nxt

    def reset_evict_count(self) -> None:
        self.set_meta("evict_count", "0")

    def add_evict_count(self, n: int) -> None:
        self.set_meta("evict_count", str(self.evict_count() + n))

    def evict_count(self) -> int:
        raw = self.get_meta("evict_count")
        return int(raw) if raw else 0

    def close(self) -> None:
        self.conn.close()
