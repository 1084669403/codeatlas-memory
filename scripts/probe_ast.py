"""EN: Probe tree-sitter AST structure to validate parser.py design assumptions.
ZH: 探查 tree-sitter AST 结构，验证 parser.py 的设计假设。
"""

from __future__ import annotations

from tree_sitter_language_pack import get_parser


def dump(node, indent: int = 0, max_depth: int = 4) -> None:
    field = ""
    pad = "  " * indent
    text = node.text.decode("utf-8", "replace").replace("\n", "\\n")[:60]
    print(f"{pad}{node.type} [{node.start_point[0] + 1}:{node.end_point[0] + 1}] {text!r}")
    if indent < max_depth:
        for i, child in enumerate(node.children):
            print(f"{pad}  child[{i}] field={node.field_name_for_child(i)!r}")
            dump(child, indent + 2, max_depth)


print("=== Python ===")
src = b'''\
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
tree = get_parser("python").parse(src)
dump(tree.root_node, max_depth=5)

print("\n=== TypeScript ===")
ts_src = b'''\
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
'''
ts_tree = get_parser("typescript").parse(ts_src)
dump(ts_tree.root_node, max_depth=4)
