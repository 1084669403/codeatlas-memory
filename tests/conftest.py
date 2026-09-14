"""EN: Shared pytest fixtures — mini sample projects (Py/JS/TS + Chinese names).
ZH: 共享 pytest fixtures —— 小型样例项目（Py/JS/TS + 中文文件名）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

PY_MAIN = '''\
"""Sample application entry."""

from .service import process


def main() -> None:
    """Run the app."""
    process(1)
'''

PY_SERVICE = '''\
"""Business service."""


def process(item_id: int) -> str:
    """Process one item."""
    return f"item-{item_id}"


class ItemService:
    """Item business logic."""

    def rename(self, item_id: int, name: str) -> bool:
        """Rename an item."""
        return True
'''

PY_UTIL = '''\
"""Helpers."""


def fmt(value: object) -> str:
    """Format any value."""
    return str(value)
'''

TS_INDEX = '''\
import { helper } from "./helper";

/**
 * Entry point.
 */
export function bootstrap(): void {
    helper("start");
}

export interface Config {
    debug: boolean;
}

export class App {
    /** Start the app. */
    start(): void {
        console.log("started");
    }
}
'''

TS_HELPER = '''\
export function helper(msg: string): string {
    return msg.toUpperCase();
}
'''


@pytest.fixture()
def sample_project(tmp_path: Path) -> Path:
    """A small mixed-language project: src/ with py + ts, incl. a Chinese filename."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "__main__.py").write_text(PY_MAIN, encoding="utf-8")
    (src / "service.py").write_text(PY_SERVICE, encoding="utf-8")
    (src / "utils.py").write_text(PY_UTIL, encoding="utf-8")
    (src / "index.ts").write_text(TS_INDEX, encoding="utf-8")
    (src / "helper.ts").write_text(TS_HELPER, encoding="utf-8")
    # Chinese filename — a real scenario on Windows/zh-CN machines
    (src / "工具.py").write_text(
        "def 打印消息(text: str) -> None:\n    '''打印文本'''\n    print(text)\n",
        encoding="utf-8",
    )
    # non-source files that must be ignored
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("function bad() {}", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "y.py").write_text("def bad(): pass", encoding="utf-8")
    return tmp_path
