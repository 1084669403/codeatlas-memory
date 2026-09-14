"""EN: Tests for file discovery (built-in ignores + .gitignore).
ZH: 文件发现测试（内置忽略 + .gitignore）。
"""

from __future__ import annotations

from pathlib import Path

from codeatlas.scanner import scan_files


def test_finds_supported_extensions(sample_project: Path) -> None:
    files = scan_files(sample_project)
    rels = {f.relative_to(sample_project).as_posix() for f in files}
    assert "src/__main__.py" in rels
    assert "src/service.py" in rels
    assert "src/index.ts" in rels
    assert "src/helper.ts" in rels
    assert "src/工具.py" in rels  # Chinese filename must be discovered


def test_builtin_ignores(sample_project: Path) -> None:
    rels = {f.relative_to(sample_project).as_posix() for f in scan_files(sample_project)}
    assert not any(r.startswith("node_modules/") for r in rels)
    assert not any(r.startswith(".venv/") for r in rels)


def test_gitignore_respected(sample_project: Path) -> None:
    (sample_project / "generated.py").write_text("def gen(): pass", encoding="utf-8")
    (sample_project / ".gitignore").write_text("generated.py\n", encoding="utf-8")
    rels = {f.relative_to(sample_project).as_posix() for f in scan_files(sample_project)}
    assert "generated.py" not in rels
    assert "src/service.py" in rels  # unrelated files unaffected


def test_sorted_by_posix_path(sample_project: Path) -> None:
    rels = [f.relative_to(sample_project).as_posix() for f in scan_files(sample_project)]
    assert rels == sorted(rels)


def test_not_a_directory(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(NotADirectoryError):
        scan_files(tmp_path / "nope")
