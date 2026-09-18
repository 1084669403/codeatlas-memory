"""EN: Storage tests: schema, upsert/replace semantics, changes immutability.
ZH: 存储测试：schema、upsert/替换语义、changes 不可变性。
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.models import (
    ChangeRecord,
    ChangeType,
    FileRecord,
    Symbol,
    SymbolKind,
    WorkingSetEntry,
)
from codeatlas.storage import Store


def _record(path: str, name: str) -> FileRecord:
    return FileRecord(
        path=path,
        language="python",
        hash="h1",
        mtime=1.0,
        size=10,
        symbols=[
            Symbol(
                qualified_name=f"m.{name}",
                name=name,
                kind=SymbolKind.FUNCTION,
                signature=f"def {name}()",
                params="()",
                returns="",
            )
        ],
    )


def test_upsert_replaces_symbols(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    store.upsert_file(_record("a.py", "old"), "2026-01-01T00:00:00+00:00")
    store.upsert_file(_record("a.py", "new"), "2026-01-01T00:00:01+00:00")
    syms = store.symbols_for_file("a.py")
    assert len(syms) == 1
    assert syms[0][2] == "new"
    store.close()


def test_changes_append_only(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    rec = ChangeRecord(
        ts="2026-01-01T00:00:00+00:00",
        file="a.py",
        symbol="m.old",
        change_type=ChangeType.REMOVED,
        old_value="def old()",
    )
    store.append_changes([rec])
    store.append_changes([rec])
    got = store.changes_for_symbol("m.old")
    assert len(got) == 2  # append-only: nothing replaced
    store.close()


def test_fts_available_and_meta(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    assert store.fts_enabled is True  # bundled sqlite >= 3.34 has trigram
    store.set_meta("lang", "zh")
    assert store.get_meta("lang") == "zh"
    store.close()


def test_wal_mode(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    store.close()


def test_v1_database_migrates_in_place(tmp_path: Path) -> None:
    """A schema-v1 db (no body, no index_version column) upgrades in place."""
    import sqlite3

    p = tmp_path / "old.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE files (path TEXT PRIMARY KEY, language TEXT NOT NULL,
            hash TEXT NOT NULL, mtime REAL NOT NULL, size INTEGER NOT NULL,
            role TEXT NOT NULL, parsed_at TEXT NOT NULL);
        CREATE TABLE symbols (file TEXT NOT NULL, qualified_name TEXT NOT NULL,
            name TEXT NOT NULL, kind TEXT NOT NULL, signature TEXT NOT NULL,
            params TEXT NOT NULL, returns TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '', role TEXT NOT NULL,
            line INTEGER NOT NULL, end_line INTEGER NOT NULL,
            language TEXT NOT NULL, bases TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (file, qualified_name));
        CREATE TABLE pages (page_id TEXT PRIMARY KEY, file TEXT NOT NULL,
            version TEXT NOT NULL, granularity TEXT NOT NULL,
            loaded_at TEXT NOT NULL, load_count INTEGER NOT NULL DEFAULT 1);
        """
    )
    conn.execute("INSERT INTO meta VALUES ('lang','en')")
    conn.commit()
    conn.close()

    store = Store(p)
    sym_cols = {r[1] for r in store.conn.execute("PRAGMA table_info(symbols)")}
    page_cols = {r[1] for r in store.conn.execute("PRAGMA table_info(pages)")}
    assert "body" in sym_cols
    assert "index_version" in page_cols
    store.close()


def test_working_set_migration_preserves_global_rows(tmp_path: Path) -> None:
    import sqlite3

    db_path = tmp_path / "old-working-set.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE working_set (
            page_id TEXT PRIMARY KEY,
            loaded_at TEXT NOT NULL,
            last_access_at TEXT NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0,
            tokens INTEGER NOT NULL DEFAULT 0,
            origin TEXT NOT NULL DEFAULT 'load'
        );
        """
    )
    conn.execute(
        "INSERT INTO working_set VALUES ('src.old.page', 't0', 't1', 1, 12, 'load')"
    )
    conn.commit()
    conn.close()

    store = Store(db_path)
    try:
        columns = {row[1] for row in store.conn.execute("PRAGMA table_info(working_set)")}
        entries = store.working_set_entries()
    finally:
        store.close()

    assert {"session_id", "plan_id", "batch_id"} <= columns
    assert entries == [
        WorkingSetEntry(
            page_id="src.old.page",
            loaded_at="t0",
            last_access_at="t1",
            pinned=True,
            tokens=12,
            origin="load",
        )
    ]


def test_working_set_scope_rows_are_isolated(tmp_path: Path) -> None:
    def entry(plan_id: str) -> WorkingSetEntry:
        return WorkingSetEntry(
            page_id="src.service.Page",
            loaded_at="t0",
            last_access_at="t1",
            tokens=10,
            plan_id=plan_id,
        )

    store = Store(tmp_path / "scoped.db")
    try:
        store.upsert_working_set(entry("plan-a"))
        store.upsert_working_set(entry("plan-b"))
        store.upsert_working_set(entry(""))

        assert len(store.working_set_entries()) == 3
        assert store.get_working_set_entry("src.service.Page", plan_id="plan-a") == entry("plan-a")
        assert store.get_working_set_entry("src.service.Page", plan_id="plan-b") == entry("plan-b")
        assert store.get_working_set_entry("src.service.Page") == entry("")

        store.delete_working_set_entry("src.service.Page", plan_id="plan-a")
        remaining = store.working_set_entries()
    finally:
        store.close()

    assert {item.plan_id for item in remaining} == {"", "plan-b"}
