from __future__ import annotations

import ast
import os
import re
from lsprotocol import types

from hmx_core.locals import class_model, local_models, model_of_expr
from hmx_core.pysource import Constants, parse_source
from hmx_ls.cursor.common import path_to_uri, range_to_lsp, uri_to_path
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor


def prepare_rename(server, uri: str, position: types.Position) -> types.PrepareRenamePlaceholder | None:
    path = uri_to_path(uri)
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return None

    line = position.line + 1
    col = position.character

    if path.endswith(".xml"):
        ctx = resolve_xml_cursor(content, line, col, server.resolver)
        if ctx and ctx.kind == "field" and ctx.value:
            return types.PrepareRenamePlaceholder(range=range_to_lsp(ctx.range), placeholder=ctx.value)
    elif path.endswith(".py"):
        ctx = resolve_py_cursor(content, line, col, server.resolver)
        if ctx and ctx.kind in ("field", "dotted_field") and ctx.value:
            f_name = ctx.value.split(".")[ctx.hop_index]
            return types.PrepareRenamePlaceholder(range=range_to_lsp(ctx.range), placeholder=f_name)
        if ctx and ctx.kind == "method" and ctx.value:
            return types.PrepareRenamePlaceholder(range=range_to_lsp(ctx.range), placeholder=ctx.value)

    return None


def resolve_rename(server, uri: str, position: types.Position, new_name: str) -> types.WorkspaceEdit | None:
    path = uri_to_path(uri)
    root = server.root
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return None

    line = position.line + 1
    col = position.character
    target_model: str | None = None
    old_field: str | None = None
    old_method: str | None = None

    if path.endswith(".xml"):
        ctx = resolve_xml_cursor(content, line, col, server.resolver)
        if ctx and ctx.kind == "field" and ctx.active_model:
            target_model = ctx.active_model
            old_field = ctx.value
    elif path.endswith(".py"):
        ctx = resolve_py_cursor(content, line, col, server.resolver)
        if ctx and ctx.kind in ("field", "dotted_field") and ctx.active_model:
            target_model = ctx.active_model
            old_field = ctx.value.split(".")[ctx.hop_index]
        elif ctx and ctx.kind == "method" and ctx.active_model:
            target_model = ctx.active_model
            old_method = ctx.value

    if not target_model or (not old_field and not old_method):
        return None

    changes: dict[str, list[types.TextEdit]] = {}

    if old_method:
        method_loc = server.resolver.methods(target_model).get(old_method)
        for py_file in server.index.file_models:
            f_uri = path_to_uri(py_file, root)
            f_doc = server.workspace.get_text_document(f_uri)
            f_content = f_doc.source if f_doc else ""
            if not f_content:
                p = os.path.join(root, py_file) if root else py_file
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        f_content = fh.read()
            if not f_content:
                continue
            try:
                tree = parse_source(f_content)
            except SyntaxError:
                continue
            constants = Constants(tree)
            lines = f_content.splitlines()
            for cls in ast.walk(tree):
                if not isinstance(cls, ast.ClassDef):
                    continue
                if class_model(cls, constants) != target_model:
                    continue
                for item in cls.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name == old_method:
                            line = lines[item.lineno - 1]
                            at = line.find(old_method, item.col_offset)
                            if at >= 0:
                                changes.setdefault(f_uri, []).append(types.TextEdit(
                                    range=types.Range(
                                        start=types.Position(line=item.lineno - 1, character=at),
                                        end=types.Position(line=item.lineno - 1, character=at + len(old_method)),
                                    ),
                                    new_text=new_name,
                                ))
                        bindings = local_models(item, target_model, server.resolver)
                        for node in ast.walk(item):
                            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                                continue
                            if node.func.attr != old_method:
                                continue
                            owner = model_of_expr(node.func.value, bindings, target_model, server.resolver)
                            if owner != target_model:
                                continue
                            start_col = node.func.end_col_offset - len(old_method)
                            changes.setdefault(f_uri, []).append(types.TextEdit(
                                range=types.Range(
                                    start=types.Position(line=node.func.end_lineno - 1, character=start_col),
                                    end=types.Position(line=node.func.end_lineno - 1, character=node.func.end_col_offset),
                                ),
                                new_text=new_name,
                            ))
        if method_loc and not changes and method_loc.path != "<framework>":
            f_uri = path_to_uri(method_loc.path, root)
            changes[f_uri] = [types.TextEdit(
                range=types.Range(
                    start=types.Position(line=method_loc.line - 1, character=0),
                    end=types.Position(line=method_loc.line - 1, character=len(old_method)),
                ),
                new_text=new_name,
            )]
        return types.WorkspaceEdit(changes=changes)

    fields = server.resolver.fields(target_model)
    decl_loc = fields.get(old_field)
    if decl_loc and decl_loc.path != "<framework>":
        decl_uri = path_to_uri(decl_loc.path, root)
        decl_doc = server.workspace.get_text_document(decl_uri)
        decl_content = decl_doc.source if decl_doc else ""
        if not decl_content:
            p = os.path.join(root, decl_loc.path) if root else decl_loc.path
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    decl_content = fh.read()

        if decl_content:
            d_lines = decl_content.splitlines()
            if 0 <= decl_loc.line - 1 < len(d_lines):
                target_line = d_lines[decl_loc.line - 1]
                idx = target_line.find(old_field)
                if idx != -1:
                    changes.setdefault(decl_uri, []).append(types.TextEdit(
                        range=types.Range(
                            start=types.Position(line=decl_loc.line - 1, character=idx),
                            end=types.Position(line=decl_loc.line - 1, character=idx + len(old_field)),
                        ),
                        new_text=new_name,
                    ))

    for py_file, models in server.index.file_models.items():
        if target_model in models:
            f_uri = path_to_uri(py_file, root)
            f_doc = server.workspace.get_text_document(f_uri)
            f_content = f_doc.source if f_doc else ""
            if not f_content:
                p = os.path.join(root, py_file) if root else py_file
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        f_content = fh.read()
            if f_content:
                for line_idx, l_str in enumerate(f_content.splitlines()):
                    if "@api." in l_str and old_field in l_str:
                        for m in re.finditer(re.escape(old_field), l_str):
                            changes.setdefault(f_uri, []).append(types.TextEdit(
                                range=types.Range(
                                    start=types.Position(line=line_idx, character=m.start()),
                                    end=types.Position(line=line_idx, character=m.end()),
                                ),
                                new_text=new_name,
                            ))

    field_pat = re.compile(rf"""<field\s+name=(['"]){re.escape(old_field)}\1""")
    for xml_file, xml_ids in server.index.xmlids.by_file.items():
        x_uri = path_to_uri(xml_file, root)
        x_doc = server.workspace.get_text_document(x_uri)
        x_content = x_doc.source if x_doc else ""
        if not x_content:
            p = os.path.join(root, xml_file) if root else xml_file
            if os.path.isfile(p):
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    x_content = fh.read()
        if x_content and old_field in x_content:
            for line_idx, l_str in enumerate(x_content.splitlines()):
                for m in field_pat.finditer(l_str):
                    val_start = m.start() + len('<field name="')
                    val_end = val_start + len(old_field)
                    changes.setdefault(x_uri, []).append(types.TextEdit(
                        range=types.Range(
                            start=types.Position(line=line_idx, character=val_start),
                            end=types.Position(line=line_idx, character=val_end),
                        ),
                        new_text=new_name,
                    ))

    return types.WorkspaceEdit(changes=changes)
