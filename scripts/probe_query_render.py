"""EN: Verify list[int]-style signatures render fully in the query table.
ZH: 验证 list[int] 风格签名在 query 表格中完整显示。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text(
            "def f(x: list[int]) -> int:\n    return x[0]\n", encoding="utf-8"
        )
        subprocess.run(
            [sys.executable, "-m", "codeatlas.cli", "scan", ".", "--lang", "en"],
            cwd=tmp, capture_output=True, text=True,
        )
        r = subprocess.run(
            [sys.executable, "-m", "codeatlas.cli", "query", "f", "."],
            cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        print(r.stdout)
        assert "list[int]" in r.stdout, "list[int] got truncated by markup parsing"
    print("QUERY RENDER OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
