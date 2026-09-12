from __future__ import annotations

import ast
import builtins
import keyword
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExprRef:
    path: str
    start: int
    end: int
    kind: str


OPERATORS = frozenset({
    "=", "!=", "<>", ">", "<", ">=", "<=", "=?", "=like", "=ilike",
    "like", "not like", "ilike", "not ilike", "in", "not in",
    "child_of", "parent_of", "any", "not any",
})

CONTEXT_FIELD_KEYS = frozenset({
    "group_by", "groupby", "default_group_by", "search_default_group_by",
    "orderby", "order",
})

OPTION_FIELD_KEYS = frozenset({
    "default_group_by", "group_by", "currency_field", "related_field",
    "color_field", "image_field", "sum", "avg",
})

MODIFIER_SKIP = frozenset({
    "True", "False", "None", "context", "uid", "active_id", "parent", "id",
})

BOOLEAN_LITERALS = frozenset({"1", "0", "true", "false"})

_LEAF_RE = re.compile(
    r"""[\(\[]\s*(?P<q>['\"])(?P<f>[^'\"]+)(?P=q)\s*,\s*(?P<p>['\"])(?P<op>[^'\"]*)(?P=p)\s*,"""
)
_REF_RE = re.compile(r"""\bref\s*\(\s*(?P<q>['\"])(?P<x>[^'\"]+)(?P=q)\s*\)""")
_PAIR_RE = re.compile(
    r"""(?P<q>['\"])(?P<k>[A-Za-z_][\w.]*)(?P=q)\s*:\s*(?:(?P<q2>['\"])(?P<v>[^'\"]*)(?P=q2))?"""
)
_IDENT_RE = re.compile(r"[A-Za-z_]\w*")
_STRING_RE = re.compile(r"""(['\"])(?:\\.|(?!\1).)*\1""", re.S)
_TEMPLATE_RE = re.compile(r"%\([^)]*\)[a-zA-Z]")

_BUILTINS = frozenset(dir(builtins))


def _line_starts(expr: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(expr):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _abs_offset(expr: str, starts: list[int], lineno: int | None, col: int | None) -> int:
    if not lineno or lineno < 1 or lineno > len(starts):
        return 0
    base = starts[lineno - 1]
    end = starts[lineno] - 1 if lineno < len(starts) else len(expr)
    line = expr[base:end]
    if not col or col <= 0:
        return base
    raw = line.encode("utf-8", "ignore")
    if col >= len(raw):
        return base + len(line)
    return base + len(raw[:col].decode("utf-8", "ignore"))


def _node_span(expr: str, starts: list[int], node: ast.AST) -> tuple[int, int]:
    start = _abs_offset(expr, starts, getattr(node, "lineno", None), getattr(node, "col_offset", None))
    end_line = getattr(node, "end_lineno", None)
    end_col = getattr(node, "end_col_offset", None)
    if end_line is None or end_col is None:
        return start, len(expr)
    return start, _abs_offset(expr, starts, end_line, end_col)


def _content_start(expr: str, starts: list[int], node: ast.AST, value: str) -> int | None:
    if not value:
        return None
    start, end = _node_span(expr, starts, node)
    seg = expr[start:end] if end > start else expr[start:]
    idx = seg.find(value)
    if idx < 0:
        return None
    return start + idx


def _str_value(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _parse(expr: str):
    text = (expr or "").strip()
    if not text:
        return None
    try:
        return ast.parse(text, mode="eval").body
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None


def _shifted(expr: str) -> int:
    text = expr or ""
    return len(text) - len(text.lstrip())


def _ordered(refs: list[ExprRef]) -> list[ExprRef]:
    seen: set[tuple[int, int, str]] = set()
    out: list[ExprRef] = []
    for ref in sorted(refs, key=lambda r: (r.start, r.end)):
        key = (ref.start, ref.end, ref.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _domain_from_ast(expr: str, starts: list[int], node: ast.AST) -> list[ExprRef]:
    out: list[ExprRef] = []
    for sub in ast.walk(node):
        if not isinstance(sub, (ast.Tuple, ast.List)) or len(sub.elts) != 3:
            continue
        field = _str_value(sub.elts[0])
        op = _str_value(sub.elts[1])
        if not field or op is None:
            continue
        if op.strip().lower() not in OPERATORS:
            continue
        start = _content_start(expr, starts, sub.elts[0], field)
        if start is None:
            continue
        out.append(ExprRef(field, start, start + len(field), "field"))
    return out


def _domain_from_regex(expr: str) -> list[ExprRef]:
    out: list[ExprRef] = []
    for m in _LEAF_RE.finditer(expr or ""):
        if m.group("op").strip().lower() not in OPERATORS:
            continue
        out.append(ExprRef(m.group("f"), m.start("f"), m.end("f"), "field"))
    return out


def parse_domain(expr: str) -> list[ExprRef]:
    if not expr:
        return []
    shift = _shifted(expr)
    body = expr[shift:]
    node = _parse(expr)
    if node is not None:
        refs = _domain_from_ast(body, _line_starts(body), node)
        return _ordered([ExprRef(r.path, r.start + shift, r.end + shift, r.kind) for r in refs])
    return _ordered(_domain_from_regex(expr))


def parse_attrs(expr: str) -> list[ExprRef]:
    return parse_domain(expr)


def _field_tokens(value: str, base: int) -> list[ExprRef]:
    out: list[ExprRef] = []
    pos = 0
    for chunk in value.split(","):
        start = pos
        pos += len(chunk) + 1
        text = chunk.strip()
        if not text:
            continue
        offset = start + (len(chunk) - len(chunk.lstrip()))
        name = text.split(":")[0].strip()
        if not name:
            continue
        out.append(ExprRef(name, base + offset, base + offset + len(name), "field"))
    return out


def _context_key_refs(key: str, key_start: int) -> list[ExprRef]:
    for prefix in ("search_default_", "default_"):
        if key.startswith(prefix) and len(key) > len(prefix):
            suffix = key[len(prefix):]
            if not suffix.isidentifier():
                return []
            start = key_start + len(prefix)
            return [ExprRef(suffix, start, start + len(suffix), "field")]
    return []


def parse_context(expr: str) -> list[ExprRef]:
    if not expr:
        return []
    shift = _shifted(expr)
    body = expr[shift:]
    starts = _line_starts(body)
    node = _parse(expr)
    out: list[ExprRef] = []
    if isinstance(node, ast.Dict):
        for key_node, value_node in zip(node.keys, node.values):
            key = _str_value(key_node) if key_node is not None else None
            if not key:
                continue
            if key in CONTEXT_FIELD_KEYS:
                value = _str_value(value_node)
                if value:
                    base = _content_start(body, starts, value_node, value)
                    if base is not None:
                        out.extend(_field_tokens(value, base + shift))
                continue
            key_start = _content_start(body, starts, key_node, key)
            if key_start is None:
                continue
            out.extend(_context_key_refs(key, key_start + shift))
        return _ordered(out)
    for m in _PAIR_RE.finditer(expr):
        key = m.group("k")
        if key in CONTEXT_FIELD_KEYS:
            value = m.group("v")
            if value:
                out.extend(_field_tokens(value, m.start("v")))
            continue
        out.extend(_context_key_refs(key, m.start("k")))
    return _ordered(out)


def parse_options(expr: str) -> list[ExprRef]:
    if not expr:
        return []
    shift = _shifted(expr)
    body = expr[shift:]
    starts = _line_starts(body)
    node = _parse(expr)
    out: list[ExprRef] = []
    if isinstance(node, ast.Dict):
        for key_node, value_node in zip(node.keys, node.values):
            key = _str_value(key_node) if key_node is not None else None
            if not key or key not in OPTION_FIELD_KEYS:
                continue
            value = _str_value(value_node)
            if not value:
                continue
            base = _content_start(body, starts, value_node, value)
            if base is None:
                continue
            out.extend(_field_tokens(value, base + shift))
        return _ordered(out)
    for m in _PAIR_RE.finditer(expr):
        if m.group("k") not in OPTION_FIELD_KEYS:
            continue
        value = m.group("v")
        if value:
            out.extend(_field_tokens(value, m.start("v")))
    return _ordered(out)


def parse_order(expr: str) -> list[ExprRef]:
    if not expr:
        return []
    out: list[ExprRef] = []
    pos = 0
    for chunk in expr.split(","):
        start = pos
        pos += len(chunk) + 1
        for token in _IDENT_RE.finditer(chunk):
            name = token.group(0)
            if name.lower() in ("asc", "desc"):
                continue
            out.append(ExprRef(name, start + token.start(), start + token.end(), "field"))
            break
    return _ordered(out)


def parse_modifier(expr: str) -> list[ExprRef]:
    if not expr:
        return []
    text = expr.strip()
    if not text or text.lower() in BOOLEAN_LITERALS:
        return []
    shift = _shifted(expr)
    body = expr[shift:]
    starts = _line_starts(body)
    node = _parse(expr)
    out: list[ExprRef] = []
    if isinstance(node, (ast.List, ast.Tuple)):
        refs = _domain_from_ast(body, starts, node)
        return _ordered([ExprRef(r.path, r.start + shift, r.end + shift, r.kind) for r in refs])
    if node is not None:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Name):
                continue
            name = sub.id
            if name in MODIFIER_SKIP or name in _BUILTINS or keyword.iskeyword(name):
                continue
            start = _abs_offset(body, starts, sub.lineno, sub.col_offset) + shift
            out.append(ExprRef(name, start, start + len(name), "field"))
        return _ordered(out)
    masked = _TEMPLATE_RE.sub(lambda m: " " * (m.end() - m.start()), expr)
    masked = _STRING_RE.sub(lambda m: " " * (m.end() - m.start()), masked)
    for m in _IDENT_RE.finditer(masked):
        name = m.group(0)
        if name in MODIFIER_SKIP or name in _BUILTINS or keyword.iskeyword(name):
            continue
        if m.start() and masked[m.start() - 1] == ".":
            continue
        out.append(ExprRef(name, m.start(), m.end(), "field"))
    return _ordered(out)


def parse_eval(expr: str) -> list[ExprRef]:
    if not expr:
        return []
    shift = _shifted(expr)
    body = expr[shift:]
    starts = _line_starts(body)
    node = _parse(expr)
    out: list[ExprRef] = []
    if node is not None:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            if not isinstance(func, ast.Name) or func.id != "ref" or not sub.args:
                continue
            value = _str_value(sub.args[0])
            if not value:
                continue
            start = _content_start(body, starts, sub.args[0], value)
            if start is None:
                continue
            out.append(ExprRef(value, start + shift, start + shift + len(value), "xmlid"))
        return _ordered(out)
    for m in _REF_RE.finditer(expr):
        out.append(ExprRef(m.group("x"), m.start("x"), m.end("x"), "xmlid"))
    return _ordered(out)


def parse_python_domain(node) -> list[ExprRef]:
    if not isinstance(node, ast.AST):
        return []
    out: list[ExprRef] = []
    for sub in ast.walk(node):
        if not isinstance(sub, (ast.Tuple, ast.List)) or len(sub.elts) != 3:
            continue
        field = _str_value(sub.elts[0])
        op = _str_value(sub.elts[1])
        if not field or op is None:
            continue
        if op.strip().lower() not in OPERATORS:
            continue
        const = sub.elts[0]
        col = getattr(const, "col_offset", None)
        if col is None:
            continue
        end_col = getattr(const, "end_col_offset", None)
        if end_col is not None and end_col - col == len(field) + 2:
            start = col + 1
            end = end_col - 1
        else:
            start = col
            end = col + len(field)
        out.append(ExprRef(field, start, end, "field"))
    return _ordered(out)


def _split_refs(expr: str, kind: str, strip_bang: bool = False) -> list[ExprRef]:
    out: list[ExprRef] = []
    pos = 0
    for chunk in (expr or "").split(","):
        start = pos
        pos += len(chunk) + 1
        text = chunk.strip()
        if not text:
            continue
        offset = start + (len(chunk) - len(chunk.lstrip()))
        if strip_bang and text.startswith("!"):
            text = text[1:].strip()
            offset = start + chunk.index(text)
            if not text:
                continue
        out.append(ExprRef(text, offset, offset + len(text), kind))
    return _ordered(out)


def refs_for_attribute(attr_name: str, expr: str) -> list[ExprRef]:
    if not attr_name or expr is None:
        return []
    if attr_name == "domain":
        return parse_domain(expr)
    if attr_name == "attrs":
        return parse_attrs(expr)
    if attr_name == "context":
        return parse_context(expr)
    if attr_name == "options":
        return parse_options(expr)
    if attr_name in ("default_order", "order"):
        return parse_order(expr)
    if attr_name in ("invisible", "readonly", "required", "column_invisible"):
        if expr.strip().lower() in BOOLEAN_LITERALS:
            return []
        return parse_modifier(expr)
    if attr_name == "eval":
        return parse_eval(expr)
    if attr_name == "groups":
        return _split_refs(expr, "xmlid", strip_bang=True)
    if attr_name in ("on_change", "onchange"):
        if expr.strip().lower() in BOOLEAN_LITERALS:
            return []
        return _split_refs(expr, "method")
    if attr_name in ("states", "statusbar_visible"):
        return _split_refs(expr, "value")
    return []
