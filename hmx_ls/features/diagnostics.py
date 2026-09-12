from __future__ import annotations

import ast
import csv
import os
import re
from collections import deque

from lsprotocol import types
from lxml import etree

from hmx_core.assets import assets_from_source
from hmx_core.expressions import refs_for_attribute
from hmx_core.manifest import owner_of
from hmx_core.naming import is_domain_keyword, is_known_model, resolve_model
from hmx_ls.cursor.common import safe_relpath, uri_to_path
from hmx_ls.cursor.js_cursor import RE_API_URL, RE_METHOD_KEY, RE_MODEL_KEY

DEAD_TAGS = {"template", "function", "delete", "report", "act_window", "value"}
SUBVIEW_TAGS = {"list", "form", "search", "kanban", "pivot", "graph", "calendar",
                "activity", "gantt", "hierarchy", "quick", "tree"}
RELATIONAL = {"ForeignKey", "OneToOneField", "ManyToManyField"}
EXPR_ATTRS = ("domain", "attrs", "context", "options", "default_order", "order",
              "invisible", "readonly", "required", "column_invisible")
XMLID_ATTRS = ("ref", "action", "inherit")
SYNTH_MODEL = re.compile(r"^(?:[a-zA-Z0-9_]+\.)?model_([a-zA-Z0-9_]+)$")
SYNTH_FIELD = re.compile(r"^(?:[a-zA-Z0-9_]+\.)?field_([a-zA-Z0-9_]+)__([a-zA-Z0-9_]+)$")
SKIP_MODIFIER_VALUES = {"1", "0", "true", "false", "True", "False"}
COMODEL_ATTRS = ("domain", "context")


def _diag(line: int, start: int, end: int, message: str, code: str,
          severity: types.DiagnosticSeverity) -> types.Diagnostic:
    return types.Diagnostic(
        range=types.Range(
            start=types.Position(line=max(0, line), character=max(0, start)),
            end=types.Position(line=max(0, line), character=max(start + 1, end)),
        ),
        message=message,
        severity=severity,
        code=code,
        source="hmx-ls",
    )


def _error(line: int, start: int, end: int, message: str, code: str) -> types.Diagnostic:
    return _diag(line, start, end, message, code, types.DiagnosticSeverity.Error)


def _warn(line: int, start: int, end: int, message: str, code: str) -> types.Diagnostic:
    return _diag(line, start, end, message, code, types.DiagnosticSeverity.Warning)


def _attr_offset(lines: list[str], line: int, attr: str, value: str) -> tuple[int, int]:
    if not 0 <= line < len(lines):
        return 0, 40
    text = lines[line]
    for quote in ('"', "'"):
        at = text.find(f"{attr}={quote}")
        if at != -1:
            start = at + len(attr) + 2
            return start, start + len(value)
    at = text.find(value)
    if at != -1:
        return at, at + len(value)
    return 0, 40


def _known_xmlid(server, ref: str, module: str | None) -> bool:
    if not ref or ref.startswith("%") or ref.startswith("$"):
        return True
    if server.index.xmlids.get(ref, module):
        return True
    records = server.index.records
    if records.action(ref, module) or records.group(ref, module) or records.menu(ref, module):
        return True
    if ref in records.rules or ref in records.reports or ref in records.sequences:
        return True
    match = SYNTH_MODEL.match(ref)
    if match and is_known_model(server.resolver, match.group(1)):
        return True
    match = SYNTH_FIELD.match(ref)
    if match:
        model = resolve_model(server.resolver, match.group(1))
        if model and match.group(2) in server.resolver.fields(model):
            return True
    return False


def _expression_scope(server, elem, model: str | None) -> tuple[str | None, bool]:
    if elem.tag != "field":
        return model, True
    name = elem.get("name")
    if not name or not model:
        return model, True
    target = server.resolver.comodel(model, name.split(".")[0])
    if target and server.resolver.known(target):
        return target, True
    return None, False


def _check_expressions(server, elem, line: int, lines: list[str], model: str | None,
                       module: str | None) -> list[types.Diagnostic]:
    out: list[types.Diagnostic] = []
    comodel, resolved = _expression_scope(server, elem, model)
    for attr in EXPR_ATTRS:
        value = elem.get(attr)
        if not value or value.strip() in SKIP_MODIFIER_VALUES:
            continue
        scope = comodel if attr in COMODEL_ATTRS else model
        if attr in COMODEL_ATTRS and not resolved:
            scope = None
        base, _ = _attr_offset(lines, line, attr, value)
        for ref in refs_for_attribute(attr, value):
            start, end = base + ref.start, base + ref.end
            if ref.kind == "field":
                if not scope or not server.resolver.known(scope):
                    continue
                if is_domain_keyword(ref.path):
                    continue
                head = ref.path.split(".")[0]
                if head in server.resolver.fields(scope):
                    continue
                out.append(_error(
                    line, start, end,
                    f"Unknown field '{head}' on model '{scope}' in {attr}=",
                    "hmx-unknown-field"))
            elif ref.kind == "xmlid" and not _known_xmlid(server, ref.path, module):
                out.append(_error(
                    line, start, end,
                    f"Unknown reference '{ref.path}' in {attr}=",
                    "hmx-unknown-xmlid"))
    return out


def _diagnose_xml(server, content: str, module: str | None) -> list[types.Diagnostic]:
    try:
        root = etree.fromstring(content.encode("utf-8"))
    except etree.XMLSyntaxError as error:
        line = max(0, (error.lineno or 1) - 1)
        return [_error(line, 0, 80, str(error), "hmx-xml-syntax-error")]

    lines = content.splitlines()
    out: list[types.Diagnostic] = []
    seen: set[tuple[str, str]] = set()

    for child in root:
        if isinstance(child.tag, str) and child.tag in DEAD_TAGS:
            line = max(0, getattr(child, "sourceline", 1) - 1)
            out.append(_warn(line, 0, 40,
                             f"Tag <{child.tag}> is silently dropped by the HMX XML loader",
                             "hmx-dead-tag"))

    for elem in root.iter():
        if not isinstance(elem.tag, str):
            continue
        line = max(0, getattr(elem, "sourceline", 1) - 1)

        raw_id = elem.get("id")
        if raw_id:
            key = (elem.tag, raw_id)
            if key in seen:
                start, end = _attr_offset(lines, line, "id", raw_id)
                out.append(_error(line, start, end,
                                  f"Duplicate XMLID '{raw_id}' declared twice in this file",
                                  "hmx-duplicate-xmlid"))
            seen.add(key)

        groups = elem.get("groups")
        if groups:
            base, _ = _attr_offset(lines, line, "groups", groups)
            for ref in refs_for_attribute("groups", groups):
                if not _known_xmlid(server, ref.path, module):
                    out.append(_error(line, base + ref.start, base + ref.end,
                                      f"Unknown security group '{ref.path}'",
                                      "hmx-unknown-group"))

        attrs = XMLID_ATTRS + (("parent",) if elem.tag == "menuitem" else ())
        for attr in attrs:
            value = elem.get(attr)
            if value and elem.tag != "xpath" and not _known_xmlid(server, value, module):
                start, end = _attr_offset(lines, line, attr, value)
                out.append(_error(line, start, end,
                                  f"Unknown reference '{value}' in {attr}=",
                                  "hmx-unknown-xmlid"))

    def walk(node, model: str) -> None:
        for child in node:
            if not isinstance(child.tag, str):
                continue
            line = max(0, getattr(child, "sourceline", 1) - 1)
            descend_into = model

            if child.tag == "field":
                name = child.get("name")
                if name:
                    head = name.split(".")[0]
                    if head not in server.resolver.fields(model):
                        start, end = _attr_offset(lines, line, "name", name)
                        out.append(_error(line, start, end,
                                          f"Unknown field '{name}' on model '{model}'",
                                          "hmx-unknown-field"))
                    elif any(isinstance(g.tag, str) and g.tag in SUBVIEW_TAGS for g in child):
                        target = server.resolver.comodel(model, head)
                        if target and server.resolver.known(target):
                            descend_into = target

                widget = child.get("widget")
                if widget and not server.index.webx.known_widget(widget):
                    start, end = _attr_offset(lines, line, "widget", widget)
                    out.append(_warn(line, start, end,
                                     f"Unknown widget '{widget}'",
                                     "hmx-unknown-widget"))

            elif child.tag == "button":
                name = child.get("name")
                kind = child.get("type")
                if (name and kind != "action" and not name.startswith("%(")
                        and name not in server.resolver.methods(model)):
                    start, end = _attr_offset(lines, line, "name", name)
                    out.append(_error(line, start, end,
                                      f"Unknown method '{name}' on model '{model}'",
                                      "hmx-unknown-method"))

            out.extend(_check_expressions(server, child, line, lines, model, module))
            walk(child, descend_into)

    for record in root.iter("record"):
        if record.get("model") != "baseuiview":
            continue
        raw_model = None
        arch = None
        for child in record:
            if not isinstance(child.tag, str) or child.tag != "field":
                continue
            if child.get("name") == "model":
                raw_model = (child.get("ref") or (child.text or "").strip()) or None
            elif child.get("name") == "arch":
                arch = child
        if not raw_model or arch is None:
            continue
        model = resolve_model(server.resolver, raw_model)
        if model is None:
            line = max(0, getattr(record, "sourceline", 1) - 1)
            out.append(_error(line, 0, 60,
                              f"Unknown model '{raw_model}' referenced by this view",
                              "hmx-unknown-model"))
            continue
        walk(arch, model)

    return out


def _model_of_class(node: ast.ClassDef) -> str | None:
    for item in node.body:
        if not isinstance(item, ast.ClassDef) or item.name != "Meta":
            continue
        for stmt in item.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if (isinstance(target, ast.Name) and target.id == "name"
                        and isinstance(stmt.value, ast.Constant)
                        and isinstance(stmt.value.value, str)):
                    return stmt.value.value.lower()
    return None


def _class_call_diagnostics(server, model: str, methods, call: ast.Call,
                            out: list[types.Diagnostic]) -> None:
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if name in RELATIONAL and call.args:
        arg = call.args[0]
        if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                and arg.value != "self"
                and not is_known_model(server.resolver, arg.value)):
            out.append(_error(arg.lineno - 1, arg.col_offset, arg.end_col_offset,
                              f"Unknown target model '{arg.value}' in {name}",
                              "hmx-unknown-model"))
    for keyword in call.keywords:
        if keyword.arg not in ("compute", "inverse", "search"):
            continue
        value = keyword.value
        if (isinstance(value, ast.Constant) and isinstance(value.value, str)
                and value.value not in methods):
            out.append(_warn(value.lineno - 1, value.col_offset, value.end_col_offset,
                             f"Method '{value.value}' referenced by {keyword.arg}= "
                             f"is not defined on '{model}'",
                             "hmx-unknown-method"))


def _class_decorator_diagnostics(server, model: str, fields, item,
                                 out: list[types.Diagnostic]) -> None:
    for decorator in item.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                and func.value.id == "api"):
            continue
        if func.attr not in ("depends", "onchange", "constrains"):
            continue
        for arg in decorator.args:
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                continue
            if is_domain_keyword(arg.value):
                continue
            current = model
            current_fields = fields
            for part in arg.value.split("."):
                if part not in current_fields:
                    out.append(_error(
                        arg.lineno - 1, arg.col_offset, arg.end_col_offset,
                        f"Unknown field '{part}' on model '{current}' "
                        f"in @api.{func.attr}",
                        "hmx-unknown-field"))
                    break
                nxt = server.resolver.comodel(current, part)
                if not nxt or not server.resolver.known(nxt):
                    break
                current = nxt
                current_fields = server.resolver.fields(nxt)


def _class_diagnostics(server, node: ast.ClassDef, out: list[types.Diagnostic]) -> None:
    model = _model_of_class(node)
    if not model or not server.resolver.known(model):
        return
    fields = server.resolver.fields(model)
    methods = server.resolver.methods(model)
    for item in node.body:
        if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call):
            _class_call_diagnostics(server, model, methods, item.value, out)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _class_decorator_diagnostics(server, model, fields, item, out)


def _env_model_diagnostic(server, node: ast.Subscript, out: list[types.Diagnostic]) -> None:
    slot = node.slice
    if (isinstance(slot, ast.Constant) and isinstance(slot.value, str)
            and not is_known_model(server.resolver, slot.value)):
        out.append(_error(slot.lineno - 1, slot.col_offset, slot.end_col_offset,
                          f"Unknown model '{slot.value}' in env[...]",
                          "hmx-unknown-model"))


def _env_ref_diagnostic(server, node: ast.Call, module: str | None,
                        out: list[types.Diagnostic]) -> None:
    owner = node.func.value
    if not ((isinstance(owner, ast.Attribute) and owner.attr == "env")
            or (isinstance(owner, ast.Name) and owner.id == "env")):
        return
    if not node.args:
        return
    arg = node.args[0]
    if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            and not _known_xmlid(server, arg.value, module)):
        out.append(_error(arg.lineno - 1, arg.col_offset, arg.end_col_offset,
                          f"Unknown XMLID '{arg.value}' in env.ref(...)",
                          "hmx-unknown-xmlid"))


def _diagnose_python(server, content: str, module: str | None) -> list[types.Diagnostic]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    class_out: list[types.Diagnostic] = []
    env_out: list[types.Diagnostic] = []
    todo = deque([tree])
    pop = todo.popleft
    push = todo.append
    while todo:
        node = pop()
        for name in node._fields:
            value = getattr(node, name, None)
            if value.__class__ is list:
                for item in value:
                    if isinstance(item, ast.AST):
                        push(item)
            elif isinstance(value, ast.AST):
                push(value)

        cls = node.__class__
        if cls is ast.Call:
            func = node.func
            if func.__class__ is ast.Attribute and func.attr == "ref":
                _env_ref_diagnostic(server, node, module, env_out)
        elif cls is ast.Subscript:
            base = node.value
            if base.__class__ is ast.Attribute and base.attr == "env":
                _env_model_diagnostic(server, node, env_out)
        elif cls is ast.ClassDef:
            _class_diagnostics(server, node, class_out)

    return class_out + env_out


def _diagnose_csv(server, content: str, module: str | None) -> list[types.Diagnostic]:
    out: list[types.Diagnostic] = []
    rows = list(csv.reader(content.splitlines()))
    for number, row in enumerate(rows[1:], start=1):
        if len(row) < 4 or not any(row):
            continue
        raw_model = row[2].strip()
        group = row[3].strip()
        if raw_model and not is_known_model(server.resolver, raw_model):
            out.append(_error(number, 0, 40,
                              f"Unknown model '{raw_model}' in security ACL",
                              "hmx-unknown-model"))
        if group and not _known_xmlid(server, group, module):
            out.append(_error(number, 0, 40,
                              f"Unknown group '{group}' in security ACL",
                              "hmx-unknown-group"))
    return out


def _diagnose_js(server, content: str) -> list[types.Diagnostic]:
    out: list[types.Diagnostic] = []
    for number, text in enumerate(content.splitlines()):
        model = None
        for match in RE_MODEL_KEY.finditer(text):
            resolved = resolve_model(server.resolver, match.group(2))
            if resolved is None and not is_known_model(server.resolver, match.group(2)):
                out.append(_error(number, match.start(2), match.end(2),
                                  f"Unknown model '{match.group(2)}' in RPC payload",
                                  "hmx-unknown-model"))
            model = resolved
            break

        if model:
            methods = server.resolver.methods(model)
            for match in RE_METHOD_KEY.finditer(text):
                name = match.group(2)
                if name and not name.startswith("_") and name not in methods:
                    out.append(_error(number, match.start(2), match.end(2),
                                      f"Unknown method '{name}' on model '{model}'",
                                      "hmx-unknown-method"))

        for match in RE_API_URL.finditer(text):
            url = match.group(2)
            if not url.startswith("/hmx_api/") or url.startswith("/hmx_api/web/"):
                continue
            if server.index.routes.get("ANY", url) is None:
                out.append(_warn(number, match.start(2), match.end(2),
                                 f"Unregistered API route '{url}'",
                                 "hmx-unknown-route"))
    return out


def _diagnose_manifest(server, path: str, content: str) -> list[types.Diagnostic]:
    module_dir = os.path.dirname(path)
    rel = safe_relpath(path, server.root)
    out: list[types.Diagnostic] = []
    for entry in assets_from_source(content, rel, module_dir):
        if entry.matches:
            continue
        line = max(0, entry.loc.line - 1)
        start = max(0, entry.loc.col)
        out.append(_warn(
            line, start, start + len(entry.pattern) + 2,
            f"Asset pattern '{entry.pattern}' in bundle '{entry.bundle}' matches no file",
            "hmx-dead-asset"))
    return out


def compute_diagnostics(server, uri: str) -> list[types.Diagnostic]:
    path = uri_to_path(uri)
    doc = server.workspace.get_text_document(uri) if server.workspace else None
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return []
    if not content:
        return []

    module = owner_of(safe_relpath(path, server.root))

    if path.endswith(".xml"):
        return _diagnose_xml(server, content, module)
    if os.path.basename(path) == "__hmx__.py":
        return _diagnose_manifest(server, path, content)
    if path.endswith(".py"):
        return _diagnose_python(server, content, module)
    if path.endswith(".csv") and "security" in path:
        return _diagnose_csv(server, content, module)
    if path.endswith(".js"):
        return _diagnose_js(server, content)
    return []
