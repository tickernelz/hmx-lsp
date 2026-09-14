from __future__ import annotations

import os

from lsprotocol import types

from hmx_ls.cursor.common import uri_to_path
from hmx_ls.cursor.js_cursor import resolve_js_cursor
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor

HMX_DECORATORS = [
    ("api.depends", 'api.depends("${1:field}")', "Recompute when these fields change"),
    ("api.onchange", 'api.onchange("${1:field}")', "Run in the form view when these fields change"),
    ("api.constrains", 'api.constrains("${1:field}")', "Validate on create and write"),
    ("api.model", "api.model", "Model-level method, no active record ids"),
    ("api.model_create_multi", "api.model_create_multi", "Batch create from a list of value dicts"),
    ("api.transition", 'api.transition("${1:state}", "${2:from}", "${3:to}")', "State machine guard"),
    ("api.depends_context", 'api.depends_context("${1:company}")', "Recompute on context key change"),
    ("api.returns", 'api.returns("${1:model}")', "Coerce the return into a recordset"),
]
MAX_ITEMS = 500


def _empty() -> types.CompletionList:
    return types.CompletionList(is_incomplete=False, items=[])


def _read(server, uri: str) -> str:
    path = uri_to_path(uri)
    doc = server.workspace.get_text_document(uri) if server.workspace else None
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return ""
    return content


def _field_items(server, model: str, detail_prefix: str = "") -> list[types.CompletionItem]:
    items: list[types.CompletionItem] = []
    entry = server.index.models.get(model)
    for name in sorted(server.resolver.fields(model)):
        comodel = server.resolver.comodel(model, name)
        kind = server.resolver.field_kind(model, name)
        if comodel:
            detail = f"-> {comodel}"
        elif kind:
            detail = kind
        else:
            detail = f"{model}.{name}"
        if detail_prefix:
            detail = f"{detail_prefix} {detail}"
        origin = ""
        if entry and name in entry.injected:
            origin = "framework"
        elif entry and name in entry.reverse:
            origin = "reverse"
        items.append(types.CompletionItem(
            label=name,
            kind=types.CompletionItemKind.Field,
            detail=detail,
            sort_text=f"{'1' if origin else '0'}{name}",
            insert_text=name,
        ))
    return items


def _model_items(server) -> list[types.CompletionItem]:
    return [
        types.CompletionItem(
            label=name,
            kind=types.CompletionItemKind.Class,
            detail=f"{len(entry.declared)} declared fields",
            insert_text=name,
        )
        for name, entry in sorted(server.index.models.items())[:MAX_ITEMS]
    ]


def _method_items(server, model: str) -> list[types.CompletionItem]:
    return [
        types.CompletionItem(
            label=name,
            kind=types.CompletionItemKind.Method,
            detail=f"{model}.{name}()",
            insert_text=name,
        )
        for name in sorted(server.resolver.methods(model))
        if not name.startswith("__")
    ]


def _widget_items(server) -> list[types.CompletionItem]:
    from hmx_core.webx import BUILTIN_WIDGETS

    items = [
        types.CompletionItem(
            label=name,
            kind=types.CompletionItemKind.Property,
            detail=f"registry: {entry.registry_type}",
            insert_text=name,
        )
        for name, entry in sorted(server.index.webx.widgets.items())
    ]
    known = {item.label for item in items}
    items.extend(
        types.CompletionItem(
            label=name,
            kind=types.CompletionItemKind.Property,
            detail="built-in widget",
            insert_text=name,
        )
        for name in sorted(BUILTIN_WIDGETS) if name not in known
    )
    return items


def _xmlid_items(server, only_groups: bool = False) -> list[types.CompletionItem]:
    records = server.index.records
    if only_groups:
        return [
            types.CompletionItem(
                label=xmlid,
                kind=types.CompletionItemKind.Constant,
                detail=entry.name or "security group",
                insert_text=xmlid,
            )
            for xmlid, entry in sorted(records.groups.items())[:MAX_ITEMS]
        ]
    items = [
        types.CompletionItem(
            label=xmlid,
            kind=types.CompletionItemKind.Reference,
            detail=entry.model or "record",
            insert_text=xmlid,
        )
        for xmlid, entry in sorted(server.index.xmlids.entries.items())[:MAX_ITEMS]
    ]
    return items


def _selection_items(server, model: str, field: str) -> list[types.CompletionItem]:
    return [
        types.CompletionItem(
            label=value,
            kind=types.CompletionItemKind.EnumMember,
            detail=f"{model}.{field}",
            insert_text=value,
        )
        for value in server.resolver.selections(model).get(field, [])
    ]


def _component_items(server) -> list[types.CompletionItem]:
    return [
        types.CompletionItem(
            label=name,
            kind=types.CompletionItemKind.Module,
            detail="Vue component",
            insert_text=name,
        )
        for name in sorted(server.index.webx.components)[:MAX_ITEMS]
    ]


def _from_xml(server, content: str, line: int, col: int) -> types.CompletionList:
    ctx = resolve_xml_cursor(content, line, col, server.resolver)
    if ctx is None:
        return _empty()

    if ctx.kind == "cssclass":
        index = getattr(server, "styles", None)
        if index is None:
            return _empty()
        prefix = ctx.value
        if ctx.range:
            typed = col - ctx.range[0][1]
            if 0 <= typed <= len(ctx.value):
                prefix = ctx.value[:typed]
        names = index.prefixed(prefix, MAX_ITEMS)
        items = [types.CompletionItem(label=name,
                                      kind=types.CompletionItemKind.Color,
                                      detail=f"{len(index.declarations(name))} declarations")
                 for name in names]
        return types.CompletionList(is_incomplete=len(items) >= MAX_ITEMS, items=items)

    if ctx.kind in ("field", "expr_field") and ctx.active_model:
        head, _, tail = ctx.value.rpartition(".")
        model = ctx.active_model
        if head:
            resolved = server.resolver.resolve_path(model, head)
            if resolved:
                stepped = server.resolver.comodel(resolved[-1][0], resolved[-1][1])
                if stepped and server.resolver.known(stepped):
                    model = stepped
        prefix = f"{ctx.attribute}:" if ctx.kind == "expr_field" else ""
        return types.CompletionList(is_incomplete=False,
                                    items=_field_items(server, model, prefix))

    if ctx.kind == "method" and ctx.active_model:
        return types.CompletionList(is_incomplete=False,
                                    items=_method_items(server, ctx.active_model))
    if ctx.kind == "model":
        return types.CompletionList(is_incomplete=False, items=_model_items(server))
    if ctx.kind == "widget":
        return types.CompletionList(is_incomplete=False, items=_widget_items(server))
    if ctx.kind == "component":
        return types.CompletionList(is_incomplete=False, items=_component_items(server))
    if ctx.kind == "selection" and ctx.active_model:
        field = "state" if ctx.attribute in ("states", "statusbar_visible") else ctx.attribute
        return types.CompletionList(is_incomplete=False,
                                    items=_selection_items(server, ctx.active_model, field or ""))
    if ctx.kind == "xmlid":
        only_groups = ctx.attribute == "groups"
        return types.CompletionList(is_incomplete=False,
                                    items=_xmlid_items(server, only_groups))
    return _empty()


def _from_python(server, content: str, line: int, col: int, current: str) -> types.CompletionList:
    prefix = current[:col].strip()
    if (prefix.startswith("@api.") or prefix in ("@api", "@")) and "(" not in prefix:
        return types.CompletionList(is_incomplete=False, items=[
            types.CompletionItem(
                label=f"@{label}",
                kind=types.CompletionItemKind.Function,
                detail=detail,
                insert_text=snippet,
                insert_text_format=types.InsertTextFormat.Snippet,
            )
            for label, snippet, detail in HMX_DECORATORS
        ])

    ctx = resolve_py_cursor(content, line, col, server.resolver)
    if ctx is None:
        return _empty()

    if ctx.kind == "model":
        return types.CompletionList(is_incomplete=False, items=_model_items(server))
    if ctx.kind == "field_prefix" and ctx.active_model:
        return types.CompletionList(is_incomplete=False,
                                    items=_field_items(server, ctx.active_model, ctx.value))
    if ctx.kind == "dotted_field" and ctx.active_model:
        model = ctx.active_model
        hops = ctx.value.split(".")[:ctx.hop_index]
        for hop in hops:
            stepped = server.resolver.comodel(model, hop)
            if not stepped or not server.resolver.known(stepped):
                break
            model = stepped
        detail = ctx.secondary_value or ""
        return types.CompletionList(is_incomplete=False,
                                    items=_field_items(server, model, detail))
    if ctx.kind == "xmlid":
        return types.CompletionList(is_incomplete=False, items=_xmlid_items(server))
    return _empty()


def _from_js(server, content: str, line: int, col: int) -> types.CompletionList:
    ctx = resolve_js_cursor(content, line, col)
    if ctx is None:
        return _empty()

    if ctx.kind == "model":
        return types.CompletionList(is_incomplete=False, items=_model_items(server))
    if ctx.kind == "method" and ctx.secondary_value:
        return types.CompletionList(is_incomplete=False,
                                    items=_method_items(server, ctx.secondary_value))
    if ctx.kind in ("component", "template"):
        return types.CompletionList(is_incomplete=False, items=_component_items(server))
    if ctx.kind == "widget":
        return types.CompletionList(is_incomplete=False, items=_widget_items(server))
    if ctx.kind == "store":
        return types.CompletionList(is_incomplete=False, items=[
            types.CompletionItem(label=name, kind=types.CompletionItemKind.Variable,
                                 detail="Pinia store", insert_text=name)
            for name in sorted(server.index.webx.stores)
        ])
    if ctx.kind == "route":
        seen: set[str] = set()
        items: list[types.CompletionItem] = []
        for (verb, route_path), entry in server.index.routes.routes.items():
            if route_path in seen:
                continue
            seen.add(route_path)
            items.append(types.CompletionItem(
                label=route_path,
                kind=types.CompletionItemKind.Function,
                detail=f"{verb} {entry.handler_name or ''}".strip(),
                insert_text=route_path,
            ))
            if len(items) >= MAX_ITEMS:
                break
        return types.CompletionList(is_incomplete=len(items) >= MAX_ITEMS, items=items)
    return _empty()


def resolve_completion(server, uri: str, position: types.Position) -> types.CompletionList:
    path = uri_to_path(uri)
    content = _read(server, uri)
    if not content:
        return _empty()

    line = position.line + 1
    col = position.character
    lines = content.splitlines()
    current = lines[line - 1] if 0 <= line - 1 < len(lines) else ""

    if path.endswith(".xml"):
        return _from_xml(server, content, line, col)
    if path.endswith(".py"):
        return _from_python(server, content, line, col, current)
    if path.endswith((".js", ".vue")):
        return _from_js(server, content, line, col)
    return _empty()
