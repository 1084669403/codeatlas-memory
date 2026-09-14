"""EN: Full CLI-level verification on a realistic mini project (incl. Chinese filename).
ZH: 对真实小型项目做 CLI 级完整验证（含中文文件名）。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

PY_V1 = '''\
"""Demo service module."""


def order_total(items: list[int]) -> int:
    """Sum order items."""
    return sum(items)


class OrderService:
    """Handles orders."""

    def place(self, item: int) -> int:
        return item
'''

PY_V2 = '''\
"""Demo service module."""


def order_total(items: list[int], discount: float = 0.0) -> float:
    """Sum order items with discount."""
    total = sum(items)
    return total * (1 - discount)


class OrderService:
    """Handles orders and payments."""

    def place(self, item: int) -> int:
        return item

    def refund(self, item: int) -> bool:
        return True
'''


def run(*args: str, cwd: Path) -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "codeatlas.cli", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout + proc.stderr).strip()
    # EN: GBK console can't print every codepoint — guard the probe output.
    # ZH: GBK 控制台无法打印全部字符 —— 探针输出做防护。
    try:
        print(f"$ codeatlas {' '.join(args)}\n{out}\n")
    except UnicodeEncodeError:
        print(f"$ codeatlas {' '.join(args)}\n{out.encode('ascii', 'replace').decode()}\n")
    return proc.returncode


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "src"
        src.mkdir()
        (src / "service.py").write_text(PY_V1, encoding="utf-8")
        # EN: Chinese filename case — our own docs are read by Chinese users too.
        # ZH: 中文文件名用例 —— 本项目文档也面向中文用户。
        (src / "工具.py").write_text("def 打印(msg: str) -> None:\n    '''打印消息'''\n    print(msg)\n", encoding="utf-8")

        assert run("scan", ".", "--lang", "zh", cwd=root) == 0
        overview = (root / "CODEATLAS.md").read_text(encoding="utf-8")
        assert "```mermaid" in overview, "mermaid blocks missing"
        assert overview.count("```mermaid") == 3, f"expected 3 diagrams, got {overview.count('```mermaid')}"
        detail_dir = root / ".codeatlas" / "detail"
        details = list(detail_dir.glob("*.md"))
        assert details, "detail shards missing"
        print("overview OK, detail files:", [p.name for p in details])

        # query zh + en
        assert run("query", "打印", cwd=root) == 0
        assert run("query", "order_total", cwd=root) == 0

        # update: modify one file
        time.sleep(0.05)
        (src / "service.py").write_text(PY_V2, encoding="utf-8")
        assert run("update", ".", "--lang", "zh", cwd=root) == 0
        hist = list((root / ".codeatlas" / "history").glob("*.md"))
        assert hist, "history doc missing"
        hist_text = hist[0].read_text(encoding="utf-8")
        assert "签名变更" in hist_text or "signature_changed" in hist_text
        assert "refund" in hist_text
        print("history doc:", hist[0].name)

        # history command: rename-free chain for a changed symbol
        assert run("history", "order_total", cwd=root) == 0

        # second update with no changes -> no re-parse
        assert run("update", ".", "--lang", "zh", cwd=root) == 0

        # self-scan guard: .codeatlas never indexed
        assert run("scan", ".", "--lang", "en", cwd=root) == 0

        # placeholders
        assert run("serve", cwd=root) == 0
        assert run("mcp", cwd=root) == 0

    print("FULL CLI E2E PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
