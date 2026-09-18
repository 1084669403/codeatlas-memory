"""EN: tree-sitter based symbol extraction for Python / JavaScript / TypeScript.
ZH: 基于 tree-sitter 的 Python / JavaScript / TypeScript 符号提取。
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from tree_sitter_language_pack import get_parser

from .models import BODY_MAX_BYTES, CallEdge, FileRecord, Import, Symbol, SymbolKind
from .scanner import EXTENSION_TO_LANGUAGE

# EN: node type -> kind mapping, per language family.
# ZH: 各语言族的 节点类型 -> 符号种类 映射。
PY_SYMBOL_NODES = {
    "function_definition": SymbolKind.FUNCTION,
    "class_definition": SymbolKind.CLASS,
}

JS_SYMBOL_NODES = {
    "function_declaration": SymbolKind.FUNCTION,
    "class_declaration": SymbolKind.CLASS,
    "abstract_class_declaration": SymbolKind.CLASS,
    "interface_declaration": SymbolKind.INTERFACE,
    "type_alias_declaration": SymbolKind.TYPE_ALIAS,
    # EN: const x = () => {} / const x = function() {} — arrow/function assigned to identifier.
    # ZH: 赋值给标识符的箭头函数/函数表达式。
    "variable_declarator": SymbolKind.FUNCTION,
}

TS_METHOD_NODES = {
    "method_definition": SymbolKind.METHOD,
    "public_field_definition": SymbolKind.METHOD,
    "abstract_method_signature": SymbolKind.METHOD,
    "method_signature": SymbolKind.METHOD,
}


@lru_cache(maxsize=8)
def _get_parser_cached(language: str):
    """Cache parsers (grammar download happens once on first use)."""
    return get_parser(language)


def _text(node) -> str:
    return node.text.decode("utf-8", "replace")


def _flatten(text: str) -> str:
    """Collapse all whitespace (incl. CRLF) to single spaces in signatures.

    EN: source files with CRLF or wrapped declarations would otherwise leak
    raw newlines into signatures and history docs.
    ZH: CRLF 或折行声明的源文件否则会把原始换行带进签名与历史文档。
    """
    return " ".join(text.split())


def _module_name(rel_posix: str) -> str:
    """EN: src/codeatlas/parser.py -> codeatlas.parser (dotted module path).
    ZH: 转成点分模块路径，用于 Python 限定名。"""
    p = rel_posix
    if p.endswith("/__init__.py"):
        p = p[: -len("/__init__.py")]
    elif p.endswith(".py"):
        p = p[: -len(".py")]
    return p.replace("/", ".")


def _js_module_key(rel_posix: str) -> str:
    """EN: strip extension for JS/TS module keys; keeps directory structure.
    ZH: JS/TS 模块键去掉扩展名，保留目录结构。"""
    for ext in (".tsx", ".ts", ".jsx", ".mjs", ".cjs", ".js"):
        if rel_posix.endswith(ext):
            return rel_posix[: -len(ext)]
    return rel_posix


def _first_docstring(body_node) -> str:
    """EN: Python docstring = first string statement in the block. Also accepts
    expression statements (bare strings).
    ZH: Python docstring = 块中第一条字符串语句（也接受裸字符串表达式语句）。"""
    if body_node is None:
        return ""
    for child in body_node.children:
        if child.type in ("string", "expression_statement"):
            inner = child
            if child.type == "expression_statement":
                inner = child.children[0] if child.children else None
                if inner is None or inner.type != "string":
                    return ""
            raw = _text(inner).strip()
            # strip triple quotes
            for q in ('"""', "'''"):
                if raw.startswith(q) and raw.endswith(q):
                    return raw[3:-3].strip()
            if raw.startswith('"') and raw.endswith('"'):
                return raw[1:-1].strip()
            if raw.startswith("'") and raw.endswith("'"):
                return raw[1:-1].strip()
            return raw
        if child.type not in ("comment",):
            return ""
    return ""


# --------------------------------------------------------------------------
# EN: call extraction + body extraction (virtual-memory stage A).
# ZH: 调用提取 + 函数体提取（虚拟内存阶段 A）。
# --------------------------------------------------------------------------

def _normalize_body(raw: str) -> str:
    """Normalize a function body for storage/diffing.

    EN: CRLF/CR -> LF, then cap at 64KB (byte-based). Normalization happens at
    extraction time so every downstream consumer sees the same text.
    ZH: CRLF/CR -> LF，再按 64KB（字节）截断。提取时即归一化，保证下游
    所有消费方看到同一份文本。
    """
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    if len(normalized.encode("utf-8", "replace")) > BODY_MAX_BYTES:
        return normalized.encode("utf-8")[:BODY_MAX_BYTES].decode("utf-8", "ignore")
    return normalized


def _body_text(body_node) -> str:
    """Extract and normalize the body text of a function-like node."""
    if body_node is None:
        return ""
    return _normalize_body(_text(body_node))


# EN: Python call expression shape: call(arguments). callee = function field
# (identifier/attribute) — arguments are NOT traversed so nested calls like
# f(g(x)) attribute g(x) to its own line and we still catch it as a separate
# call only if we walk; plan says collect call text as written, one per call node.
# ZH: Python 调用表达式形态：call(arguments)。callee 取 function 字段
# （identifier/attribute）。
def _py_calls_in_body(src_qname: str, body_node) -> list[CallEdge]:
    """Collect raw call edges from a Python function body (non-recursive walk
    of the body, recursive within nested call chains)."""
    if body_node is None:
        return []
    edges: list[CallEdge] = []

    def visit(node) -> None:
        if node.type == "call":
            func = node.child_by_field_name("function")
            if func is not None and func.type in ("identifier", "attribute"):
                edges.append(
                    CallEdge(
                        src_qname=src_qname,
                        callee_raw=_text(func).strip(),
                        line=node.start_point[0] + 1,
                    )
                )
            # EN: still descend — chained/nested calls each get their own edge.
            # ZH: 继续下钻 —— 链式/嵌套调用各自成边。
            for child in node.children:
                visit(child)
            return
        # EN: do not descend into nested function/class definitions — their
        # calls belong to the inner symbol.
        # ZH: 不进入嵌套函数/类定义 —— 其调用属于内层符号。
        if node.type in ("function_definition", "class_definition"):
            return
        for child in node.children:
            visit(child)

    visit(body_node)
    return edges


def _js_calls_in_body(src_qname: str, body_node) -> list[CallEdge]:
    """Collect raw call edges from a JS/TS function/method body."""
    if body_node is None:
        return []
    edges: list[CallEdge] = []

    def visit(node) -> None:
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func is not None and func.type in (
                "identifier",
                "member_expression",
            ):
                edges.append(
                    CallEdge(
                        src_qname=src_qname,
                        callee_raw=_text(func).strip(),
                        line=node.start_point[0] + 1,
                    )
                )
            for child in node.children:
                visit(child)
            return
        if node.type in (
            "function_declaration",
            "function_expression",
            "arrow_function",
            "class_declaration",
        ):
            return  # inner symbols own their calls
        for child in node.children:
            visit(child)

    visit(body_node)
    return edges


def _preceding_jsdoc(siblings, index: int) -> str:
    """EN: JSDoc = nearest preceding comment ending on the previous line(s).
    ZH: JSDoc = 紧邻前方、以 */ 结束的注释块。"""
    i = index - 1
    while i >= 0:
        sib = siblings[i]
        if sib.type == "comment":
            txt = _text(sib).strip()
            if txt.startswith("/**"):
                return txt.strip("/*").strip().lstrip("*").strip()
            return ""  # a non-doc comment sits between: stop
        break
    return ""


def _parse_py_signature(node) -> tuple[str, str, str]:
    """Extract (signature, params, returns) from a Python function/class node."""
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    ret_node = node.child_by_field_name("return_type")
    name = _text(name_node) if name_node else "<anonymous>"
    params = _flatten(_text(params_node)) if params_node else "()"
    params = params.strip()
    if params == "":
        params = "()"
    returns = _flatten(_text(ret_node)).strip() if ret_node else ""
    if node.type == "class_definition":
        sig = f"class {name}"
        bases = _py_class_bases(node)
        if bases:
            sig += f"({', '.join(bases)})"
        return sig, "()", ""
    sig = f"def {name}{params}"
    if returns:
        sig += f" -> {returns}"
    return sig, params, returns


def _parse_js_signature(node) -> tuple[str, str, str]:
    """Extract (signature, params, returns) from a JS/TS declaration node.

    EN: return_type field is a type_annotation whose text includes the leading
    ':' — strip it to keep signature rendering consistent.
    ZH: return_type 字段是 type_annotation 节点，文本含前导冒号 —— 去掉以保持
    签名渲染一致。
    """
    name_node = node.child_by_field_name("name")
    params_node = node.child_by_field_name("parameters")
    ret_node = node.child_by_field_name("return_type")
    name = _text(name_node) if name_node else "<anonymous>"
    params = _flatten(_text(params_node)).strip() if params_node else "()"
    returns = _flatten(_text(ret_node)).strip() if ret_node else ""
    if returns.startswith(":"):
        returns = returns[1:].strip()

    if node.type in ("class_declaration", "abstract_class_declaration"):
        sig = f"class {name}"
        # EN: append heritage text (extends/implements) verbatim for readability.
        # ZH: 原样追加继承文本（extends/implements）以便阅读。
        for child in node.children:
            if child.type in ("class_heritage", "implements_clause", "extends_clause"):
                sig += f" {_flatten(_text(child)).strip()}"
    elif node.type == "interface_declaration":
        sig = f"interface {name}"
    elif node.type == "type_alias_declaration":
        sig = f"type {name}"
    else:
        sig = f"function {name}{params}"
        if returns:
            sig += f": {returns}"
    return sig, params, returns


def _js_class_bases(node) -> list[str]:
    """Extract base classes / implemented interfaces of a JS/TS class.

    EN: Heritage text looks like "extends Base implements Op, Runnable";
    keywords are converted to separators so each name splits cleanly.
    ZH: 继承文本形如 "extends Base implements Op, Runnable"；
    把关键字替换为分隔符后即可干净拆分。
    """
    import re

    for child in node.children:
        if child.type in ("class_heritage", "implements_clause", "extends_clause"):
            txt = _text(child)
            txt = re.sub(r"\bextends\b|\bimplements\b", ",", txt)
            return [p.strip() for p in txt.split(",") if p.strip()]
    return []


def _py_class_bases(node) -> list[str]:
    """Extract superclass names from a Python class_definition argument_list."""
    supers = node.child_by_field_name("superclasses")
    if supers is None:
        return []
    bases: list[str] = []
    for child in supers.children:
        if child.type == "identifier":
            bases.append(_text(child))
        elif child.type == "attribute":
            bases.append(_text(child))
        elif child.type == "keyword_argument":
            continue  # metaclass=... is not a base
    return bases


def _extract_js_imports(root) -> list[Import]:
    """Extract import statements (source path + names) from JS/TS AST."""
    imports: list[Import] = []

    def walk(node):
        if node.type == "import_statement":
            source_node = node.child_by_field_name("source")
            source = _text(source_node).strip().strip("\"'") if source_node else ""
            names: list[str] = []
            # import_clause: { a, b as c }  |  default, { named }  |  * as ns
            for child in node.children:
                if child.type in ("import_clause",):
                    txt = _text(child)
                    inner = txt.strip().strip("{}")
                    names.extend(
                        n.strip().split(" as ")[-1].strip()
                        for n in inner.split(",")
                        if n.strip()
                    )
            imports.append(Import(source=source, names=names))
        for child in node.children:
            walk(child)

    walk(root)
    return imports


def _extract_py_imports(root) -> list[Import]:
    """Extract Python import statements (module path + names)."""
    imports: list[Import] = []

    def walk(node):
        if node.type == "import_from_statement":
            mod_node = node.child_by_field_name("module_name")
            mod = _text(mod_node) if mod_node else ""
            names = [
                _text(c)
                for c in node.children
                if c.type == "dotted_name" and _text(c) != mod
            ]
            # also handle 'as' aliases: name as alias -> report alias
            imports.append(Import(source=mod, names=names))
        elif node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    imports.append(Import(source=_text(child), names=[]))
        if node.type not in ("function_definition", "class_definition"):
            for child in node.children:
                walk(child)

    walk(root)
    return imports


def _python_symbols(rel_posix: str, source: bytes, root) -> list[Symbol]:
    """Extract symbols from a Python AST (top-level + class methods)."""
    symbols: list[Symbol] = []
    calls: list[CallEdge] = []  # virtual-memory stage A output
    module = _module_name(rel_posix)

    def visit(node, class_prefix: str, parent_siblings=None):
        for i, child in enumerate(node.children):
            if child.type == "decorated_definition":
                definition = next(
                    (
                        item
                        for item in child.named_children
                        if item.type in ("function_definition", "class_definition")
                    ),
                    None,
                )
                if definition is not None:
                    visit(child, class_prefix)
                continue
            if child.type == "function_definition":
                sig, params, returns = _parse_py_signature(child)
                name = _text(child.child_by_field_name("name"))
                qual = f"{module}.{class_prefix}{name}" if class_prefix else f"{module}.{name}"
                doc = _first_docstring(child.child_by_field_name("body"))
                kind = SymbolKind.METHOD if class_prefix else SymbolKind.FUNCTION
                symbols.append(
                    Symbol(
                        qualified_name=qual,
                        name=name,
                        kind=kind,
                        signature=sig,
                        params=params,
                        returns=returns,
                        docstring=doc,
                        line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        language="python",
                        body=_body_text(child.child_by_field_name("body")),
                    )
                )
                calls.extend(_py_calls_in_body(qual, child.child_by_field_name("body")))
            elif child.type == "class_definition":
                sig, params, _ = _parse_py_signature(child)
                name = _text(child.child_by_field_name("name"))
                qual = f"{module}.{class_prefix}{name}" if class_prefix else f"{module}.{name}"
                doc = _first_docstring(child.child_by_field_name("body"))
                bases = _py_class_bases(child)
                symbols.append(
                    Symbol(
                        qualified_name=qual,
                        name=name,
                        kind=SymbolKind.CLASS,
                        signature=sig,
                        params=params,
                        returns="",
                        docstring=doc,
                        bases=bases,
                        line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        language="python",
                    )
                )
                # recurse into class body for methods (nested classes keep prefix)
                body = child.child_by_field_name("body")
                if body is not None:
                    visit(body, f"{class_prefix}{name}.")

    visit(root, "")
    return symbols, calls


def _js_symbols(rel_posix: str, source: bytes, root) -> tuple[list[Symbol], list[CallEdge]]:
    """Extract symbols from a JS/TS AST (top-level + class members + TS types)."""
    symbols: list[Symbol] = []
    calls: list[CallEdge] = []  # virtual-memory stage A output
    module = _js_module_key(rel_posix)
    language = "typescript" if rel_posix.endswith((".ts", ".tsx")) else "javascript"

    def add_symbol(sym: Symbol) -> None:
        symbols.append(sym)

    def handle_declaration(node, class_prefix: str) -> None:
        t = node.type
        if t == "variable_declarator":
            # only function-valued: const f = () => {} | function() {}
            value = node.child_by_field_name("value")
            if value is None or value.type not in ("arrow_function", "function_expression"):
                return
            name_node = node.child_by_field_name("name")
            name = _text(name_node) if name_node else ""
            if not name:
                return
            params_node = value.child_by_field_name("parameters")
            ret_node = value.child_by_field_name("return_type")
            params = _flatten(_text(params_node)).strip() if params_node else "()"
            returns = _flatten(_text(ret_node)).strip() if ret_node else ""
            # EN: type_annotation text includes the leading ':' — normalize.
            # ZH: type_annotation 文本含前导冒号 —— 统一去除。
            if returns.startswith(":"):
                returns = returns[1:].strip()
            sig = f"function {name}{params}"
            if returns:
                sig += f": {returns}"
            qual = f"{module}{('.' + class_prefix + name) if class_prefix else ('.' + name)}"
            add_symbol(
                Symbol(
                    qualified_name=qual,
                    name=name,
                    kind=SymbolKind.FUNCTION,
                    signature=sig,
                    params=params,
                    returns=returns,
                    line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    language=language,
                    body=_body_text(value.child_by_field_name("body")),
                )
            )
            calls.extend(_js_calls_in_body(qual, value.child_by_field_name("body")))
            return
        if t not in JS_SYMBOL_NODES:
            return
        sig, params, returns = _parse_js_signature(node)
        name_node = node.child_by_field_name("name")
        name = _text(name_node) if name_node else "<anonymous>"
        qual = f"{module}{('.' + class_prefix + name) if class_prefix else ('.' + name)}"
        kind = JS_SYMBOL_NODES[t]
        add_symbol(
            Symbol(
                qualified_name=qual,
                name=name,
                kind=kind,
                signature=sig,
                params=params,
                returns=returns,
                bases=_js_class_bases(node) if t in ("class_declaration", "abstract_class_declaration") else [],
                line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language=language,
                body=_body_text(node.child_by_field_name("body")),
            )
        )
        if t in ("function_declaration",):
            calls.extend(_js_calls_in_body(qual, node.child_by_field_name("body")))
        if t in ("class_declaration", "abstract_class_declaration"):
            body = node.child_by_field_name("body")
            if body is not None:
                visit_class_body(body, name)

    def visit_class_body(body, class_name: str) -> None:
        body_children = list(body.children)
        for idx, child in enumerate(body_children):
            if child.type == "method_definition":
                sig, params, returns = _parse_js_signature(child)
                name_node = child.child_by_field_name("name")
                name = _text(name_node).strip() if name_node else "<anonymous>"
                qual = f"{module}.{class_name}.{name}"
                method_body = child.child_by_field_name("body")
                add_symbol(
                    Symbol(
                        qualified_name=qual,
                        name=name,
                        kind=SymbolKind.METHOD,
                        signature=f"{name}{params}",
                        params=params,
                        returns=returns,
                        docstring=_preceding_jsdoc(body_children, idx),
                        line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        language=language,
                        body=_body_text(method_body),
                    )
                )
                calls.extend(_js_calls_in_body(qual, method_body))
            elif child.type == "public_field_definition":
                name_node = child.child_by_field_name("name")
                value = child.child_by_field_name("value")
                if value is not None and value.type in ("arrow_function", "function_expression"):
                    name = _text(name_node).strip() if name_node else ""
                    params_node = value.child_by_field_name("parameters")
                    params = _text(params_node).strip() if params_node else "()"
                    qual = f"{module}.{class_name}.{name}"
                    field_body = value.child_by_field_name("body")
                    add_symbol(
                        Symbol(
                            qualified_name=qual,
                            name=name,
                            kind=SymbolKind.METHOD,
                            signature=f"{name}{params}",
                            params=params,
                            returns="",
                            docstring=_preceding_jsdoc(body_children, idx),
                            line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1,
                            language=language,
                            body=_body_text(field_body),
                        )
                    )
                    calls.extend(_js_calls_in_body(qual, field_body))
            elif child.type in ("abstract_class_declaration", "class_declaration"):
                # nested class
                handle_declaration(child, f"{class_name}.")

    def visit(node) -> None:
        for i, child in enumerate(node.children):
            # EN: export_statement wraps declarations; unwrap to the 'declaration' field.
            # ZH: export_statement 包裹声明；解包到 declaration 字段。
            if child.type == "export_statement":
                decl = child.child_by_field_name("declaration")
                if decl is not None:
                    if decl.type in JS_SYMBOL_NODES:
                        # attach preceding JSDoc from the export statement's siblings
                        doc = _preceding_jsdoc(node.children, i)
                        handle_declaration(decl, "")
                        if symbols and not symbols[-1].docstring:
                            symbols[-1].docstring = doc
                    else:
                        visit(decl)
                continue
            if child.type in JS_SYMBOL_NODES:
                doc = _preceding_jsdoc(node.children, i)
                handle_declaration(child, "")
                if symbols and not symbols[-1].docstring:
                    symbols[-1].docstring = doc
                continue
            if child.type in ("lexical_declaration", "variable_declaration"):
                for decl in child.children:
                    if decl.type == "variable_declarator":
                        doc = _preceding_jsdoc(child.children, list(child.children).index(decl))
                        handle_declaration(decl, "")
                        if symbols and not symbols[-1].docstring and doc:
                            symbols[-1].docstring = doc
                continue
            # EN: recurse into statements/blocks (functions, if/for bodies, namespaces)
            # ZH: 递归进入语句/块（函数体、if/for、命名空间）。
            if child.type not in (
                "comment",
                "import_statement",
                "function_declaration",
                "class_declaration",
                "abstract_class_declaration",
            ):
                visit(child)

    visit(root)
    return symbols, calls


def parse_file(root: Path, file_path: Path) -> FileRecord:
    """Parse one file into a FileRecord (symbols + imports + hash).

    EN: The returned FileRecord.path is a repo-relative POSIX path so that
    the same codebase yields identical keys across platforms (Windows/mac/linux).
    ZH: 返回的 FileRecord.path 是仓库相对 POSIX 路径，保证同一代码库
    跨平台（Windows/mac/linux）键一致。
    """
    rel_posix = file_path.relative_to(root).as_posix()
    suffix = file_path.suffix.lower()
    language = EXTENSION_TO_LANGUAGE.get(suffix, "")
    if not language:
        raise ValueError(f"unsupported file type: {file_path}")

    source = file_path.read_bytes()
    # EN: tsx/jsx parse with the tsx parser (JSX syntax support).
    # ZH: tsx/jsx 用 tsx 解析器（支持 JSX 语法）。
    parser_lang = "tsx" if suffix in (".tsx", ".jsx") else language
    parser = _get_parser_cached(parser_lang)
    tree = parser.parse(source)

    if language == "python":
        symbols, calls = _python_symbols(rel_posix, source, tree.root_node)
        imports = _extract_py_imports(tree.root_node)
    else:
        symbols, calls = _js_symbols(rel_posix, source, tree.root_node)
        imports = _extract_js_imports(tree.root_node)

    stat = file_path.stat()
    return FileRecord(
        path=rel_posix,
        language=language,
        hash=hashlib.sha256(source).hexdigest(),
        mtime=stat.st_mtime,
        size=stat.st_size,
        symbols=symbols,
        imports=imports,
        calls=calls,
    )
