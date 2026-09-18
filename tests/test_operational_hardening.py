"""Tests for operational hardening: GBK console, plan slug, Go parser."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import yaml
import pytest

from codeatlas.cli import _safe_console_encoding
from codeatlas.models import SymbolKind
from codeatlas.parser import parse_file
from codeatlas.plans import _slugify

GO_SAMPLE = '''package main

import (
	"fmt"
	"strings"
)

// Greeter provides greeting behavior.
type Greeter interface {
	Greet(name string) string
}

// Person represents a named entity.
type Person struct {
	Name string
	Age  int
}

func NewPerson(name string, age int) *Person {
	return &Person{Name: name, Age: age}
}

func (p *Person) Greet(name string) string {
	return fmt.Sprintf("Hello, %s from %s", name, p.Name)
}

func helper(x string) string {
	return strings.ToUpper(x)
}
'''


class TestSafeConsoleEncoding:
    """Verify CLI console output does not raise UnicodeEncodeError on GBK."""

    def test_stdout_reconfigured_to_replace_errors(self) -> None:
        _safe_console_encoding()
        assert sys.stdout is not None
        assert getattr(sys.stdout, "errors", None) == "replace"

    def test_stderr_reconfigured_to_replace_errors(self) -> None:
        _safe_console_encoding()
        assert sys.stderr is not None
        assert getattr(sys.stderr, "errors", None) == "replace"

    def test_unicode_output_does_not_raise(self) -> None:
        _safe_console_encoding()
        gbk_stream = io.TextIOWrapper(io.BytesIO(), encoding="gbk", errors="replace")
        gbk_stream.write("hello — arrow → 中文 ✓")
        gbk_stream.flush()
        gbk_stream.close()


class TestSlugifyDatePrefix:
    """Verify _slugify strips leading date prefixes to prevent double-dated IDs."""

    def test_slug_with_leading_date_is_stripped(self) -> None:
        assert _slugify("2026-09-18-plan-evidence-lifecycle") == "plan-evidence-lifecycle"

    def test_slug_without_date_is_unchanged(self) -> None:
        assert _slugify("operational-hardening") == "operational-hardening"

    def test_slug_with_embedded_date_is_kept(self) -> None:
        assert _slugify("fix-2026-09-18-bug") == "fix-2026-09-18-bug"

    def test_slug_with_multiple_date_prefixes(self) -> None:
        assert _slugify("2026-09-18-2026-09-18-plan") == "2026-09-18-plan"

    def test_slug_date_only_becomes_plan(self) -> None:
        assert _slugify("2026-09-18") == "plan"

    def test_slug_with_slash_date_normalized(self) -> None:
        assert _slugify("2026/09/18 my plan") == "my-plan"


class TestCIMatrix:
    """Verify the CI workflow includes macOS in the pytest matrix."""

    def _load_ci_yaml(self) -> dict:
        ci_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
        with open(ci_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_macos_in_matrix(self) -> None:
        ci = self._load_ci_yaml()
        matrix = ci["jobs"]["test"]["strategy"]["matrix"]
        all_oses = list(matrix["os"]) + [e["os"] for e in matrix.get("include", [])]
        assert "macos-latest" in all_oses

    def test_macos_python_version(self) -> None:
        ci = self._load_ci_yaml()
        includes = ci["jobs"]["test"]["strategy"]["matrix"]["include"]
        macos_entries = [e for e in includes if e.get("os") == "macos-latest"]
        assert len(macos_entries) >= 1
        assert macos_entries[0]["python-version"] == "3.13"


class TestGoParser:
    """Verify Go source files are parsed into symbols, imports, and calls."""

    def test_go_file_parsed(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        assert rec.language == "go"
        assert len(rec.symbols) > 0

    def test_go_function_symbol(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        funcs = [s for s in rec.symbols if s.kind == SymbolKind.FUNCTION]
        names = {s.name for s in funcs}
        assert "NewPerson" in names
        assert "helper" in names

    def test_go_method_symbol(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        methods = [s for s in rec.symbols if s.kind == SymbolKind.METHOD]
        assert len(methods) >= 1
        assert methods[0].name == "Greet"
        assert ".Person." in methods[0].qualified_name

    def test_go_struct_symbol(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        structs = [s for s in rec.symbols if s.kind == SymbolKind.CLASS]
        assert any(s.name == "Person" for s in structs)

    def test_go_interface_symbol(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        interfaces = [s for s in rec.symbols if s.kind == SymbolKind.INTERFACE]
        assert any(s.name == "Greeter" for s in interfaces)
        greeter = next(s for s in interfaces if s.name == "Greeter")
        assert "Greet" in greeter.bases

    def test_go_imports(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        sources = {i.source for i in rec.imports}
        assert "fmt" in sources
        assert "strings" in sources

    def test_go_calls(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        callees = {c.callee_raw for c in rec.calls}
        assert "fmt.Sprintf" in callees
        assert "strings.ToUpper" in callees

    def test_go_docstring(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        person = next(s for s in rec.symbols if s.name == "Person" and s.kind == SymbolKind.CLASS)
        assert "Person" in person.docstring

    def test_go_language_not_python_or_js(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(GO_SAMPLE, encoding="utf-8")
        rec = parse_file(tmp_path, go_file)
        assert rec.language not in ("python", "javascript", "typescript")
