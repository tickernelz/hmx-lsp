from __future__ import annotations

import os
from lsprotocol import types

from hmx_ls.cursor.common import uri_to_path
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor

HMX_DECORATORS = [
    ("api.depends", "api.depends(\"${1:field}\")", "Compute field dependency declaration"),
    ("api.onchange", "api.onchange(\"${1:field}\")", "Client-side field change trigger"),
    ("api.constrains", "api.constrains(\"${1:field}\")", "Validation constraint on fields"),
    ("api.model", "api.model", "Method callable on model recordset"),
    ("api.model_create_multi", "api.model_create_multi", "Batch record creation optimization"),
    ("api.transition", "api.transition(\"${1:state_field}\", \"${2:from_state}\", \"${3:to_state}\")", "Workflow state transition guard"),
    ("api.depends_context", "api.depends_context(\"${1:company}\")", "Context-dependent compute declaration"),
    ("api.returns", "api.returns(\"${1:model}\")", "Return type adapter wrapping in recordset"),
]


def resolve_completion(server, uri: str, position: types.Position) -> types.CompletionList:
    path = uri_to_path(uri)
    root = server.root
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return types.CompletionList(is_incomplete=False, items=[])

    line = position.line + 1
    col = position.character
    lines = content.splitlines()
    curr_line = lines[line - 1] if 0 <= line - 1 < len(lines) else ""

    if path.endswith(".xml"):
        ctx = resolve_xml_cursor(content, line, col, server.resolver)
        if ctx and ctx.kind == "field" and ctx.active_model:
            model = ctx.active_model
            fields = server.resolver.fields(model)
            items = []
            for f_name in sorted(fields.keys()):
                comodel = server.resolver.comodel(model, f_name)
                detail = f"-> {comodel}" if comodel else f"{model}.{f_name}"
                items.append(types.CompletionItem(
                    label=f_name,
                    kind=types.CompletionItemKind.Field,
                    detail=detail,
                    insert_text=f_name,
                ))
            return types.CompletionList(is_incomplete=False, items=items)

        if ctx and (ctx.kind == "model" or ctx.attribute == "model"):
            items = [
                types.CompletionItem(
                    label=m,
                    kind=types.CompletionItemKind.Class,
                    detail=f"HMX Model ({len(server.resolver.fields(m))} fields)",
                    insert_text=m,
                )
                for m in sorted(server.index.models.keys())
            ]
            return types.CompletionList(is_incomplete=False, items=items)

        if ctx and ctx.kind == "widget":
            items = [
                types.CompletionItem(
                    label=w_name,
                    kind=types.CompletionItemKind.Property,
                    detail=f"Webx Widget ({entry.registry_type})",
                    insert_text=w_name,
                )
                for w_name, entry in sorted(server.index.webx.widgets.items())
            ]
            return types.CompletionList(is_incomplete=False, items=items)

        if ctx and (ctx.kind == "xmlid" or ctx.attribute == "groups"):
            items = [
                types.CompletionItem(
                    label=xid,
                    kind=types.CompletionItemKind.Reference,
                    detail=entry.model or "XMLID",
                    insert_text=xid,
                )
                for xid, entry in sorted(server.index.xmlids.entries.items())
            ]
            return types.CompletionList(is_incomplete=False, items=items)

    elif path.endswith(".py"):
        prefix = curr_line[:col].strip()
        if (prefix.startswith("@api.") or prefix == "@api" or prefix == "@") and "(" not in curr_line[:col]:
            items = [
                types.CompletionItem(
                    label=f"@{label}",
                    kind=types.CompletionItemKind.Function,
                    detail=detail,
                    insert_text=snippet,
                    insert_text_format=types.InsertTextFormat.Snippet,
                )
                for label, snippet, detail in HMX_DECORATORS
            ]
            return types.CompletionList(is_incomplete=False, items=items)

        ctx = resolve_py_cursor(content, line, col)
        if ctx and ctx.kind == "model":
            items = [
                types.CompletionItem(
                    label=m,
                    kind=types.CompletionItemKind.Class,
                    detail="HMX Model",
                    insert_text=m,
                )
                for m in sorted(server.index.models.keys())
            ]
            return types.CompletionList(is_incomplete=False, items=items)

        if ctx and ctx.kind == "dotted_field" and ctx.active_model:
            curr = ctx.active_model
            if "." in ctx.value:
                hops = ctx.value.split(".")
                for h in hops[:ctx.hop_index]:
                    curr = server.resolver.comodel(curr, h)
                    if not curr:
                        break

            if curr:
                fields = server.resolver.fields(curr)
                dec_info = f" ({ctx.secondary_value})" if ctx.secondary_value else ""
                items = [
                    types.CompletionItem(
                        label=f_name,
                        kind=types.CompletionItemKind.Field,
                        detail=f"{curr}.{f_name}{dec_info}",
                        insert_text=f_name,
                    )
                    for f_name in sorted(fields.keys())
                ]
                return types.CompletionList(is_incomplete=False, items=items)

    return types.CompletionList(is_incomplete=False, items=[])
