"""EN: File discovery with built-in ignores plus .gitignore support.
ZH: 文件发现：内置忽略规则 + .gitignore 支持。
"""

from __future__ import annotations

import os
from pathlib import Path

import pathspec

# EN: Extensions mapped to parser language names.
# ZH: 扩展名到解析器语言名的映射。
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
}

# EN: Directories always excluded, independent of .gitignore.
# ZH: 永远排除的目录（不依赖 .gitignore）。
BUILTIN_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        ".codeatlas",  # never index our own artifacts
    }
)

# EN: File names always excluded (lock files etc. — huge and low-value to index).
# ZH: 永远排除的文件（lock 文件等——体积大且索引价值低）。
BUILTIN_IGNORED_FILES: frozenset[str] = frozenset(
    {
        ".gitignore",
        ".gitattributes",
        "uv.lock",
        "poetry.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
    }
)


def load_gitignore_spec(root: Path) -> pathspec.GitIgnoreSpec | None:
    """Load the root .gitignore as a pathspec, if present and non-empty.

    EN: Only the root .gitignore is read (nested ones add complexity for
    little value in indexing). Returns None when missing or unreadable.
    ZH: 只读根目录 .gitignore（嵌套规则对索引价值低、复杂度高）。
    文件不存在或不可读时返回 None。
    """
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return None
    try:
        lines = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if not any(line.strip() and not line.lstrip().startswith("#") for line in lines):
        return None
    try:
        return pathspec.GitIgnoreSpec.from_lines(lines)
    except Exception:
        return None


def scan_files(root: Path) -> list[Path]:
    """Walk the tree and return scannable files, sorted by relative POSIX path.

    EN: Applies (1) built-in dir/file excludes, (2) root .gitignore rules.
    os.walk with in-place pruning skips ignored directories without
    descending into them. Sorting guarantees stable, directory-ordered
    output downstream (a core project requirement).
    ZH: 依次应用 (1) 内置目录/文件排除，(2) 根 .gitignore 规则。
    os.walk 原地剪枝可直接跳过忽略目录不入内。按 POSIX 相对路径排序，
    保证下游输出稳定且按目录序排列（项目核心需求）。
    """
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")

    spec = load_gitignore_spec(root)
    found: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        # EN: prune ignored dirs in-place so walk never enters them.
        # ZH: 原地剪枝忽略目录，遍历不会进入。
        dirnames[:] = sorted(d for d in dirnames if d not in BUILTIN_IGNORED_DIRS)
        for fname in sorted(filenames):
            if fname in BUILTIN_IGNORED_FILES:
                continue
            rel = (rel_dir / fname) if str(rel_dir) != "." else Path(fname)
            rel_posix = rel.as_posix()
            if spec is not None and spec.match_file(rel_posix):
                continue
            if Path(fname).suffix.lower() in EXTENSION_TO_LANGUAGE:
                found.append(root / rel)

    return sorted(found, key=lambda p: p.relative_to(root).as_posix())
