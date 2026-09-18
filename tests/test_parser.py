"""EN: Tests for tree-sitter symbol extraction (py/js/ts, docstrings, bases).
ZH: tree-sitter 符号提取测试（py/js/ts、文档字符串、基类）。
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.parser import parse_file


def test_python_symbols(sample_project: Path) -> None:
    rec = parse_file(sample_project, sample_project / "src" / "service.py")
    assert rec.language == "python"
    names = {s.qualified_name for s in rec.symbols}
    assert "src.service.process" in names
    assert "src.service.ItemService" in names
    assert "src.service.ItemService.rename" in names

    fn = next(s for s in rec.symbols if s.name == "process")
    assert fn.signature == "def process(item_id: int) -> str"
    assert fn.returns == "str"
    assert fn.docstring == "Process one item."

    cls = next(s for s in rec.symbols if s.name == "ItemService")
    assert cls.kind.value == "class"
    method = next(s for s in rec.symbols if s.name == "rename")
    assert method.kind.value == "method"


def test_python_magic_and_roles(sample_project: Path) -> None:
    rec = parse_file(sample_project, sample_project / "src" / "__main__.py")
    assert any(s.name == "main" for s in rec.symbols)


def test_python_decorated_definitions_are_symbols(tmp_path: Path) -> None:
    module = tmp_path / "decorated.py"
    module.write_text(
        "from dataclasses import dataclass\n"
        "\n"
        "def register(name):\n"
        "    def wrapper(target):\n"
        "        return target\n"
        "    return wrapper\n"
        "\n"
        "@register('command')\n"
        "def command() -> str:\n"
        "    '''Run a command.'''\n"
        "    return 'ok'\n"
        "\n"
        "@dataclass\n"
        "class Config:\n"
        "    name: str\n"
        "\n"
        "    @staticmethod\n"
        "    def default() -> 'Config':\n"
        "        return Config('default')\n",
        encoding="utf-8",
    )

    rec = parse_file(tmp_path, module)
    names = {symbol.qualified_name for symbol in rec.symbols}

    assert "decorated.command" in names
    assert "decorated.Config" in names
    assert "decorated.Config.default" in names


def test_typescript_symbols(sample_project: Path) -> None:
    rec = parse_file(sample_project, sample_project / "src" / "index.ts")
    assert rec.language == "typescript"
    kinds = {s.name: s.kind.value for s in rec.symbols}
    assert kinds["bootstrap"] == "function"
    assert kinds["Config"] == "interface"
    assert kinds["App"] == "class"
    assert kinds["start"] == "method"

    boot = next(s for s in rec.symbols if s.name == "bootstrap")
    assert boot.docstring == "Entry point."
    start = next(s for s in rec.symbols if s.name == "start")
    assert start.docstring == "Start the app."  # method-level JSDoc


def test_ts_imports(sample_project: Path) -> None:
    rec = parse_file(sample_project, sample_project / "src" / "index.ts")
    assert any(i.source == "./helper" for i in rec.imports)


def test_chinese_filename_symbols(sample_project: Path) -> None:
    rec = parse_file(sample_project, sample_project / "src" / "工具.py")
    names = {s.qualified_name for s in rec.symbols}
    assert "src.工具.打印消息" in names
    sym = next(s for s in rec.symbols if s.name == "打印消息")
    assert sym.docstring == "打印文本"


def test_posix_relative_path(sample_project: Path) -> None:
    rec = parse_file(sample_project, sample_project / "src" / "service.py")
    assert "\\" not in rec.path  # cross-platform key stability
