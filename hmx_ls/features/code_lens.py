from __future__ import annotations

import ast
import os
from lsprotocol import types
from lxml import etree

from hmx_ls.cursor.common import uri_to_path

VIEW_MODEL = "baseuiview"
META_NAME_KEYS = ("name", "model_name")


def resolve_code_lens(server, uri: str) -> list[types.CodeLens]:
    path = uri_to_path(uri)
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return []

    if not content:
        return []
    if path.endswith(".py"):
        return _python_lenses(server, content)
    if path.endswith(".xml"):
        return _xml_lenses(content)
    return []


def _python_lenses(server, content: str) -> list[types.CodeLens]:
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return []
    out: list[types.CodeLens] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        model = _meta_model(node)
        if model is None:
            continue
        fields = sum(1 for stmt in node.body if _is_field(stmt))
        methods = sum(1 for stmt in node.body
                      if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)))
        views = _view_count(server, model)
        title = f"{fields} fields | {methods} methods | {views} views"
        out.append(_lens(node.lineno, title))
    return out


def _meta_model(node: ast.ClassDef) -> str | None:
    for stmt in node.body:
        if not isinstance(stmt, ast.ClassDef) or stmt.name != "Meta":
            continue
        for inner in stmt.body:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(inner, ast.Assign):
                targets = list(inner.targets)
                value = inner.value
            elif isinstance(inner, ast.AnnAssign):
                targets = [inner.target]
                value = inner.value
            for target in targets:
                if not isinstance(target, ast.Name) or target.id not in META_NAME_KEYS:
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
                return ""
    return None


def _is_field(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Assign):
        return isinstance(stmt.value, ast.Call)
    if isinstance(stmt, ast.AnnAssign):
        return isinstance(stmt.value, ast.Call)
    return False


def _view_count(server, model: str) -> int:
    if not model:
        return 0
    try:
        mapping = getattr(server.index.xmlids, "models", None)
    except Exception:
        return 0
    if not isinstance(mapping, dict):
        return 0
    got = mapping.get(model)
    if not got:
        return 0
    try:
        return len(got)
    except TypeError:
        return 0


def _xml_lenses(content: str) -> list[types.CodeLens]:
    try:
        root = etree.fromstring(content.encode("utf-8"))
    except (etree.XMLSyntaxError, ValueError):
        return []
    out: list[types.CodeLens] = []
    for record in root.iter("record"):
        if record.get("model") != VIEW_MODEL:
            continue
        fields = {child.get("name"): child for child in record
                  if isinstance(child.tag, str) and child.tag == "field" and child.get("name")}
        model = _value(fields.get("model"))
        if not model:
            continue
        arch = fields.get("arch")
        count = 0
        if arch is not None:
            count = sum(1 for desc in arch.iterdescendants()
                        if isinstance(desc.tag, str) and desc.tag == "field" and desc.get("name"))
        out.append(_lens(record.sourceline or 1, f"model: {model} | {count} fields"))
    return out


def _value(node) -> str | None:
    if node is None:
        return None
    ref = node.get("ref")
    if ref:
        return ref
    text = (node.text or "").strip()
    return text or None


def _lens(line: int, title: str) -> types.CodeLens:
    zero = max(0, line - 1)
    position = types.Position(line=zero, character=0)
    return types.CodeLens(range=types.Range(start=position, end=position),
                          command=types.Command(title=title, command=""))
