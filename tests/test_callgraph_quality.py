"""Tests for callgraph quality: relative import resolution, Go-aware callgraph."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeatlas.indexer import _resolve_imports
from codeatlas.indexer import run_scan
from codeatlas.models import FileRecord, Import
from codeatlas.parser import parse_file
from codeatlas.callgraph import _module_prefix, callees_of
from codeatlas.storage import Store


class TestRelativeImportResolution:
    """Verify Python relative imports resolve to project files."""

    def test_level1_with_module(self) -> None:
        rec = FileRecord(
            path="src/codeatlas/cli.py", language="python",
            hash="x", mtime=0, size=0, symbols=[], calls=[],
            imports=[Import(source=".plans", names=["PlanError"])],
        )
        paths = {"src/codeatlas/cli.py", "src/codeatlas/plans.py"}
        edges = _resolve_imports(rec, paths)
        assert ("src/codeatlas/cli.py", "src/codeatlas/plans.py") in [(e[0], e[1]) for e in edges]

    def test_level1_bare_dot(self) -> None:
        rec = FileRecord(
            path="src/codeatlas/cli.py", language="python",
            hash="x", mtime=0, size=0, symbols=[], calls=[],
            imports=[Import(source=".", names=["service"])],
        )
        paths = {"src/codeatlas/cli.py", "src/codeatlas/service.py", "src/codeatlas/__init__.py"}
        edges = _resolve_imports(rec, paths)
        dsts = [e[1] for e in edges]
        assert "src/codeatlas/service.py" in dsts

    def test_level2(self) -> None:
        rec = FileRecord(
            path="src/codeatlas/sub/mod.py", language="python",
            hash="x", mtime=0, size=0, symbols=[], calls=[],
            imports=[Import(source="..plans", names=["PlanError"])],
        )
        paths = {"src/codeatlas/sub/mod.py", "src/codeatlas/plans.py"}
        edges = _resolve_imports(rec, paths)
        assert ("src/codeatlas/sub/mod.py", "src/codeatlas/plans.py") in [(e[0], e[1]) for e in edges]

    def test_absolute_import_still_works(self) -> None:
        rec = FileRecord(
            path="src/main.py", language="python",
            hash="x", mtime=0, size=0, symbols=[], calls=[],
            imports=[Import(source="src.codeatlas.models", names=["Symbol"])],
        )
        paths = {"src/main.py", "src/codeatlas/models.py"}
        edges = _resolve_imports(rec, paths)
        assert ("src/main.py", "src/codeatlas/models.py") in [(e[0], e[1]) for e in edges]

    def test_external_import_skipped(self) -> None:
        rec = FileRecord(
            path="src/main.py", language="python",
            hash="x", mtime=0, size=0, symbols=[], calls=[],
            imports=[Import(source="json", names=[])],
        )
        paths = {"src/main.py"}
        edges = _resolve_imports(rec, paths)
        assert len(edges) == 0


class TestGoModulePrefix:
    """Verify _module_prefix handles .go files."""

    def test_go_file(self) -> None:
        assert _module_prefix("pkg/server/handler.go") == "pkg.server.handler"

    def test_go_index(self) -> None:
        assert _module_prefix("pkg/server/go.mod") == "pkg.server.go.mod"

    def test_go_nested(self) -> None:
        assert _module_prefix("cmd/api/main.go") == "cmd.api.main"


GO_SOURCE = '''package main

import (
	"fmt"
	"strings"
)

type Greeter interface {
	Greet(name string) string
}

type Person struct {
	Name string
}

func NewPerson(name string) *Person {
	return &Person{Name: name}
}

func (p *Person) Greet(name string) string {
	return fmt.Sprintf("Hello, %s! I am %s.", name, p.Name)
}

func helper(s string) string {
	return strings.ToUpper(s)
}

func main() {
	p := NewPerson("Atlas")
	msg := p.Greet("world")
	fmt.Println(helper(msg))
}
'''


class TestGoEndToEnd:
    """Verify Go source files are indexed and calls resolved end-to-end."""

    def test_go_call_resolution(self, tmp_path: Path) -> None:
        (tmp_path / "main.go").write_text(GO_SOURCE, encoding="utf-8")
        store = Store(tmp_path / ".codeatlas" / "state.db")
        run_scan(tmp_path, store)
        # Bare name calls should resolve
        callees_of_main = callees_of(store, "main.main")
        assert "main.NewPerson" in callees_of_main
        assert "main.helper" in callees_of_main
        # Method call via attribute (p.Greet) should resolve Greet
        assert "main.Person.Greet" in callees_of_main
        store.close()
