"""EN: Dependency smoke test — verify tree-sitter parsers work in this environment.
ZH: 依赖冒烟测试 —— 验证 tree-sitter 解析器在当前环境可用。

Run: uv run python scripts/smoke_test.py
"""

from __future__ import annotations

from tree_sitter_language_pack import get_parser


def main() -> None:
    cases = [
        ("python", b"def hello(name: str) -> str:\n    return name\n"),
        ("javascript", b"class Foo { bar() { return 1; } }\n"),
        ("typescript", b"export function add(a: number, b: number): number { return a + b; }\n"),
        ("tsx", b"const x = <div className=\"a\">hi</div>;\n"),
    ]
    for lang, src in cases:
        parser = get_parser(lang)
        tree = parser.parse(src)
        assert not tree.root_node.has_error, f"{lang} parse failed: {src!r}"
        print(f"[ok] {lang}: root={tree.root_node.type}")

    # Show Python AST structure for reference.
    py_tree = get_parser("python").parse(cases[0][1])
    print("python children:", [c.type for c in py_tree.root_node.children])
    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    main()
