"""EN: End-to-end smoke test for scan -> update -> diff flow.
ZH: scan -> update -> diff 流程端到端冒烟测试。
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from codeatlas.indexer import run_scan, run_update
from codeatlas.storage import Store

PY_V1 = '''\
def calc(a: int, b: int) -> int:
    """Add two ints."""
    return a + b
'''

PY_V2 = '''\
def calc(a: int, b: int) -> int:
    """Add two ints with a guard."""
    if a < 0 or b < 0:
        raise ValueError("negative")
    return a + b


def helper(x: str) -> str:
    """New helper."""
    return x.strip()
'''


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "src").mkdir()
        (root / "src" / "math.py").write_text(PY_V1, encoding="utf-8")
        (root / "src" / "util.py").write_text("def trim(s: str) -> str:\n    return s.strip()\n", encoding="utf-8")

        db = root / "state.db"
        store = Store(db)

        # --- scan ---
        r1 = run_scan(root, store, output_lang="en")
        print(f"scan: files={r1.files_scanned} parsed={r1.files_parsed} symbols={r1.symbols_found}")
        print(f"  fts_enabled={store.fts_enabled}")

        # --- update with no changes ---
        time.sleep(0.01)
        r2 = run_update(root, store, output_lang="en")
        print(f"update(nochange): parsed={r2.files_parsed} skipped={r2.files_skipped} changes={len(r2.changes)}")
        assert r2.files_parsed == 0, "no file should be re-parsed"

        # --- modify one file, delete another ---
        time.sleep(0.02)
        (root / "src" / "math.py").write_text(PY_V2, encoding="utf-8")
        (root / "src" / "util.py").unlink()
        r3 = run_update(root, store, output_lang="en")
        print(f"update(change): parsed={r3.files_parsed} skipped={r3.files_skipped}")
        for ch in r3.changes:
            print(f"  {ch.change_type.value:18} {ch.symbol}  old={ch.old_value!r} new={ch.new_value!r}")

        # --- lang switch triggers full rescan ---
        r4 = run_update(root, store, output_lang="zh")
        print(f"update(langswitch): parsed={r4.files_parsed} skipped={r4.files_skipped} (sentinel -1 expected)")

        store.close()
        print("E2E SMOKE PASSED")


if __name__ == "__main__":
    main()
