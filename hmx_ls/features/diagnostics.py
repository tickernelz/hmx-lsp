from __future__ import annotations

import ast
import csv
import os
import re
from lsprotocol import types
from lxml import etree

from hmx_core.manifest import owner_of
from hmx_core.security import normalize_model_id
from hmx_ls.cursor.common import uri_to_path
from hmx_ls.cursor.js_cursor import RE_API_URL, RE_CALL_KW_METHOD, RE_CALL_KW_MODEL

DEAD_TAGS = {"template", "function", "delete", "report", "act_window", "value"}
SUBVIEW_TAGS = {"list", "form", "search", "kanban", "pivot", "graph", "calendar",
                "activity", "gantt", "hierarchy", "quick", "tree"}
RELATIONAL_FIELDS = {"ForeignKey", "OneToOneField", "ManyToManyField"}
SYNTH_MODEL_RE = re.compile(r"^(?:[a-zA-Z0-9_]+\.)?model_([a-zA-Z0-9_]+)$")
SYNTH_FIELD_RE = re.compile(r"^(?:[a-zA-Z0-9_]+\.)?field_([a-zA-Z0-9_]+)__([a-zA-Z0-9_]+)$")
BUILTIN_ENV_MODELS = {"user", "group", "contenttype", "permission"}


def compute_diagnostics(server, uri: str) -> list[types.Diagnostic]:
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

    rel_path = os.path.relpath(path, server.root) if server.root else path
    current_module = owner_of(rel_path)

    if path.endswith(".xml"):
        return _diagnose_xml(server, content, current_module)
    if path.endswith(".py"):
        return _diagnose_python(server, content, current_module)
    if path.endswith(".csv") and "security" in path:
        return _diagnose_csv(server, content, current_module)
    if path.endswith(".js"):
        return _diagnose_js(server, content)

    return []


def _is_valid_xmlid_ref(server, ref: str, current_module: str | None) -> bool:
    if server.index.xmlids.get(ref, current_module):
        return True
    m_match = SYNTH_MODEL_RE.match(ref)
    if m_match:
        norm = normalize_model_id(m_match.group(1))
        if server.resolver.known(norm) or norm in BUILTIN_ENV_MODELS:
            return True
    f_match = SYNTH_FIELD_RE.match(ref)
    if f_match:
        norm = normalize_model_id(f_match.group(1))
        field_name = f_match.group(2)
        if server.resolver.known(norm):
            fields = server.resolver.fields(norm)
            if field_name in fields:
                return True
    return False


def _diagnose_xml(server, content: str, current_module: str | None) -> list[types.Diagnostic]:
    diags: list[types.Diagnostic] = []
    try:
        root = etree.fromstring(content.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        line = max(0, (e.lineno or 1) - 1)
        return [types.Diagnostic(
            range=types.Range(
                start=types.Position(line=line, character=0),
                end=types.Position(line=line, character=80),
            ),
            message=str(e),
            severity=types.DiagnosticSeverity.Error,
            code="hmx-xml-syntax-error",
            source="hmx-ls",
        )]

    seen_ids: set[tuple[str, str]] = set()

    for child in root:
        tag = child.tag
        if isinstance(tag, str) and tag in DEAD_TAGS:
            line = max(0, getattr(child, "sourceline", 1) - 1)
            diags.append(types.Diagnostic(
                range=types.Range(
                    start=types.Position(line=line, character=0),
                    end=types.Position(line=line, character=40),
                ),
                message=f"Tag <{tag}> is dropped by the HMX XML loader",
                severity=types.DiagnosticSeverity.Warning,
                code="hmx-dead-tag",
                source="hmx-ls",
            ))

    for elem in root.iter():
        if not isinstance(elem.tag, str):
            continue
        line = max(0, getattr(elem, "sourceline", 1) - 1)

        raw_id = elem.get("id")
        if raw_id:
            key = (elem.tag, raw_id)
            if key in seen_ids:
                diags.append(types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=line, character=0),
                        end=types.Position(line=line, character=40),
                    ),
                    message=f"Duplicate XMLID declaration '{raw_id}' in this file",
                    severity=types.DiagnosticSeverity.Error,
                    code="hmx-duplicate-xmlid",
                    source="hmx-ls",
                ))
            else:
                seen_ids.add(key)

        groups_val = elem.get("groups")
        if groups_val:
            for g in groups_val.split(","):
                group_name = g.strip()
                if group_name and group_name != "base.group_no_one":
                    if not server.index.xmlids.get(group_name, current_module):
                        diags.append(types.Diagnostic(
                            range=types.Range(
                                start=types.Position(line=line, character=0),
                                end=types.Position(line=line, character=60),
                            ),
                            message=f"Unknown security group '{group_name}'",
                            severity=types.DiagnosticSeverity.Error,
                            code="hmx-unknown-group",
                            source="hmx-ls",
                        ))

        ref_val = elem.get("ref") or elem.get("action")
        if ref_val and elem.tag != "xpath":
            if not ref_val.startswith("%") and not _is_valid_xmlid_ref(server, ref_val, current_module):
                diags.append(types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=line, character=0),
                        end=types.Position(line=line, character=60),
                    ),
                    message=f"Unknown XMLID reference '{ref_val}'",
                    severity=types.DiagnosticSeverity.Error,
                    code="hmx-unknown-xmlid",
                    source="hmx-ls",
                ))

    def check_arch(node, current_model: str):
        for child in node:
            if not isinstance(child.tag, str):
                continue
            line = max(0, getattr(child, "sourceline", 1) - 1)
            if child.tag == "field":
                fname = child.get("name")
                if fname:
                    fields = server.resolver.fields(current_model)
                    if fname not in fields:
                        diags.append(types.Diagnostic(
                            range=types.Range(
                                start=types.Position(line=line, character=0),
                                end=types.Position(line=line, character=60),
                            ),
                            message=f"Unknown field '{fname}' on model '{current_model}'",
                            severity=types.DiagnosticSeverity.Error,
                            code="hmx-unknown-field",
                            source="hmx-ls",
                        ))
                widget = child.get("widget")
                if widget and not server.index.webx.known_widget(widget):
                    diags.append(types.Diagnostic(
                        range=types.Range(
                            start=types.Position(line=line, character=0),
                            end=types.Position(line=line, character=60),
                        ),
                        message=f"Unknown widget '{widget}'",
                        severity=types.DiagnosticSeverity.Warning,
                        code="hmx-unknown-widget",
                        source="hmx-ls",
                    ))

                if fname and any(isinstance(g.tag, str) and g.tag in SUBVIEW_TAGS for g in child):
                    target = server.resolver.comodel(current_model, fname.split(".")[0])
                    if target and server.resolver.known(target):
                        check_arch(child, target)
                        continue

            check_arch(child, current_model)

    for record in root.iter("record"):
        if record.get("model") != "baseuiview":
            continue
        model_name = None
        arch_node = None
        for f in record:
            if isinstance(f.tag, str) and f.tag == "field":
                if f.get("name") == "model":
                    model_name = (f.text or "").strip() or None
                elif f.get("name") == "arch":
                    arch_node = f

        if model_name and arch_node is not None:
            norm_view_model = normalize_model_id(model_name)
            if not server.resolver.known(norm_view_model):
                line = max(0, getattr(record, "sourceline", 1) - 1)
                diags.append(types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=line, character=0),
                        end=types.Position(line=line, character=60),
                    ),
                    message=f"Unknown model '{model_name}' referenced in view",
                    severity=types.DiagnosticSeverity.Error,
                    code="hmx-unknown-model",
                    source="hmx-ls",
                ))
            else:
                check_arch(arch_node, norm_view_model)

    return diags


def _diagnose_python(server, content: str, current_module: str | None) -> list[types.Diagnostic]:
    diags: list[types.Diagnostic] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            model_name = None
            for item in node.body:
                if isinstance(item, ast.ClassDef) and item.name == "Meta":
                    for stmt in item.body:
                        if isinstance(stmt, ast.Assign):
                            for target in stmt.targets:
                                if isinstance(target, ast.Name) and target.id == "name":
                                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                        model_name = stmt.value.value.lower()
            if not model_name or not server.resolver.known(model_name):
                continue

            for item in node.body:
                if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call):
                    call = item.value
                    func_name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
                    if func_name in RELATIONAL_FIELDS and call.args:
                        arg0 = call.args[0]
                        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                            raw_target = arg0.value
                            if raw_target != "self":
                                target_model = raw_target.split(".")[-1].lower()
                                if not server.resolver.known(target_model) and target_model not in BUILTIN_ENV_MODELS:
                                    line = max(0, arg0.lineno - 1)
                                    diags.append(types.Diagnostic(
                                        range=types.Range(
                                            start=types.Position(line=line, character=arg0.col_offset),
                                            end=types.Position(line=line, character=arg0.end_col_offset),
                                        ),
                                        message=f"Unknown target model '{target_model}' in {func_name}",
                                        severity=types.DiagnosticSeverity.Error,
                                        code="hmx-unknown-model",
                                        source="hmx-ls",
                                    ))

                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in item.decorator_list:
                        if isinstance(dec, ast.Call):
                            func = dec.func
                            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "api":
                                dec_name = func.attr
                                if dec_name in ("depends", "onchange", "constrains"):
                                    for arg in dec.args:
                                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                            path_parts = arg.value.split(".")
                                            curr = model_name
                                            for part in path_parts:
                                                fields = server.resolver.fields(curr)
                                                if part not in fields:
                                                    line = max(0, arg.lineno - 1)
                                                    diags.append(types.Diagnostic(
                                                        range=types.Range(
                                                            start=types.Position(line=line, character=arg.col_offset),
                                                            end=types.Position(line=line, character=arg.end_col_offset),
                                                        ),
                                                        message=f"Unknown field '{part}' on model '{curr}' in @api.{dec_name}",
                                                        severity=types.DiagnosticSeverity.Error,
                                                        code="hmx-unknown-field",
                                                        source="hmx-ls",
                                                    ))
                                                    break
                                                curr = server.resolver.comodel(curr, part)
                                                if not curr:
                                                    break

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            base = node.value
            is_env = isinstance(base, ast.Attribute) and base.attr == "env"
            if is_env and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                target_model = node.slice.value.split(".")[-1].lower()
                if not server.resolver.known(target_model) and target_model not in BUILTIN_ENV_MODELS:
                    line = max(0, node.slice.lineno - 1)
                    diags.append(types.Diagnostic(
                        range=types.Range(
                            start=types.Position(line=line, character=node.slice.col_offset),
                            end=types.Position(line=line, character=node.slice.end_col_offset),
                        ),
                        message=f"Unknown model '{target_model}' in env[...]",
                        severity=types.DiagnosticSeverity.Error,
                        code="hmx-unknown-model",
                        source="hmx-ls",
                    ))

        if isinstance(node, ast.Call):
            func = node.func
            is_env_ref = isinstance(func, ast.Attribute) and func.attr == "ref" and (
                (isinstance(func.value, ast.Attribute) and func.value.attr == "env") or
                (isinstance(func.value, ast.Name) and func.value.id == "env")
            )
            if is_env_ref and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    xid = arg0.value
                    if not _is_valid_xmlid_ref(server, xid, current_module):
                        line = max(0, arg0.lineno - 1)
                        diags.append(types.Diagnostic(
                            range=types.Range(
                                start=types.Position(line=line, character=arg0.col_offset),
                                end=types.Position(line=line, character=arg0.end_col_offset),
                            ),
                            message=f"Unknown XMLID '{xid}' in env.ref(...)",
                            severity=types.DiagnosticSeverity.Error,
                            code="hmx-unknown-xmlid",
                            source="hmx-ls",
                        ))

    return diags


def _diagnose_csv(server, content: str, current_module: str | None) -> list[types.Diagnostic]:
    diags: list[types.Diagnostic] = []
    lines = content.splitlines()
    reader = csv.reader(lines)
    header = None
    for row_num, row in enumerate(reader, start=1):
        if not row or not any(row):
            continue
        if header is None:
            header = [c.strip().lower() for c in row]
            continue
        if len(row) < 4:
            continue
        model_col = row[2].strip()
        group_col = row[3].strip() or None

        norm_model = normalize_model_id(model_col)
        if not server.resolver.known(norm_model) and norm_model not in BUILTIN_ENV_MODELS:
            diags.append(types.Diagnostic(
                range=types.Range(
                    start=types.Position(line=row_num - 1, character=0),
                    end=types.Position(line=row_num - 1, character=40),
                ),
                message=f"Unknown model '{norm_model}' in security ACL",
                severity=types.DiagnosticSeverity.Error,
                code="hmx-unknown-model",
                source="hmx-ls",
            ))

        if group_col and not server.index.xmlids.get(group_col, current_module):
            diags.append(types.Diagnostic(
                range=types.Range(
                    start=types.Position(line=row_num - 1, character=0),
                    end=types.Position(line=row_num - 1, character=40),
                ),
                message=f"Unknown group '{group_col}' in security ACL",
                severity=types.DiagnosticSeverity.Error,
                code="hmx-unknown-group",
                source="hmx-ls",
            ))

    return diags


def _diagnose_js(server, content: str) -> list[types.Diagnostic]:
    diags: list[types.Diagnostic] = []
    lines = content.splitlines()
    for line_idx, line_str in enumerate(lines):
        for m in RE_CALL_KW_MODEL.finditer(line_str):
            model_name = m.group(2).split(".")[-1].lower()
            if not server.resolver.known(model_name) and model_name not in BUILTIN_ENV_MODELS:
                diags.append(types.Diagnostic(
                    range=types.Range(
                        start=types.Position(line=line_idx, character=m.start(2)),
                        end=types.Position(line=line_idx, character=m.end(2)),
                    ),
                    message=f"Unknown model '{model_name}' in call_kw",
                    severity=types.DiagnosticSeverity.Error,
                    code="hmx-unknown-model",
                    source="hmx-ls",
                ))

        for m in RE_CALL_KW_METHOD.finditer(line_str):
            method_name = m.group(2)
            model_name = None
            for mm in RE_CALL_KW_MODEL.finditer(line_str):
                model_name = mm.group(2).split(".")[-1].lower()
                break
            if model_name and (server.resolver.known(model_name) or model_name in BUILTIN_ENV_MODELS):
                methods = server.resolver.methods(model_name)
                if method_name not in methods and not method_name.startswith("_"):
                    diags.append(types.Diagnostic(
                        range=types.Range(
                            start=types.Position(line=line_idx, character=m.start(2)),
                            end=types.Position(line=line_idx, character=m.end(2)),
                        ),
                        message=f"Unknown method '{method_name}' on model '{model_name}' (or inherited classes) in call_kw",
                        severity=types.DiagnosticSeverity.Error,
                        code="hmx-unknown-method",
                        source="hmx-ls",
                    ))

        for m in RE_API_URL.finditer(line_str):
            url_path = m.group(2)
            if url_path.startswith("/hmx_api/") and not url_path.startswith("/hmx_api/web/"):
                route = server.index.routes.get("ANY", url_path)
                if not route:
                    diags.append(types.Diagnostic(
                        range=types.Range(
                            start=types.Position(line=line_idx, character=m.start(2)),
                            end=types.Position(line=line_idx, character=m.end(2)),
                        ),
                        message=f"Unregistered API route '{url_path}'",
                        severity=types.DiagnosticSeverity.Warning,
                        code="hmx-unknown-route",
                        source="hmx-ls",
                    ))

    return diags
