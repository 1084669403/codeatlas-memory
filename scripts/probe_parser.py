"""EN: Quick parser validation against the AST probe samples.
ZH: 用 AST 探查样例快速验证 parser 正确性。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from codeatlas.parser import parse_file

PY_SRC = '''\
def hello(name: str, age: int = 5) -> str:
    """Greet someone."""
    return name


class Greeter(BaseGreeter, metaclass=Meta):
    """A greeter class."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    def greet(self, name: str) -> str:
        return self.prefix + name
'''

TS_SRC = '''\
import { helper } from "./util";
import type { Config } from "./types";

/**
 * Adds two numbers.
 */
export function add(a: number, b: number): number {
    return a + b;
}

export class Calculator implements Op {
    /** Multiply */
    multiply(x: number, y: number): number {
        return x * y;
    }
}

export interface Shape {
    area(): number;
}

export type Alias = string | number;

export const arrow = (x: number): number => x * 2;
'''


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "app").mkdir()
        (root / "app" / "greeter.py").write_text(PY_SRC, encoding="utf-8")
        (root / "app" / "calc.ts").write_text(TS_SRC, encoding="utf-8")

        rec = parse_file(root, root / "app" / "greeter.py")
        print("=== app/greeter.py ===")
        print("hash:", rec.hash[:12], "lang:", rec.language)
        print("imports:", [(i.source, i.names) for i in rec.imports])
        for s in rec.symbols:
            print(f"  {s.kind.value:9} {s.qualified_name}  [{s.line}-{s.end_line}]")
            print(f"            sig={s.signature!r} doc={s.docstring!r} bases={s.bases}")

        rec2 = parse_file(root, root / "app" / "calc.ts")
        print("\n=== app/calc.ts ===")
        print("hash:", rec2.hash[:12], "lang:", rec2.language)
        print("imports:", [(i.source, i.names) for i in rec2.imports])
        for s in rec2.symbols:
            print(f"  {s.kind.value:9} {s.qualified_name}  [{s.line}-{s.end_line}]")
            print(f"            sig={s.signature!r} doc={s.docstring!r} bases={s.bases}")


if __name__ == "__main__":
    main()
