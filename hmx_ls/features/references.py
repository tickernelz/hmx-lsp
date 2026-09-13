from __future__ import annotations

import os

from lsprotocol import types

from hmx_ls.cursor.common import loc_to_range, path_to_uri, uri_to_path
from hmx_ls.cursor.js_cursor import resolve_js_cursor
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor


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


def _location(server, loc) -> types.Location | None:
    if loc is None or loc.path == "<framework>":
        return None
    return types.Location(uri=path_to_uri(loc.path, server.root), range=loc_to_range(loc))


def _model_references(server, model: str) -> list[types.Location]:
    out: list[types.Location] = []
    entry = server.index.models.get(model)
    if entry:
        for site in entry.sites:
            found = _location(server, site)
            if found:
                out.append(found)

    for xmlid in server.index.xmlids.models.get(model, []):
        record = server.index.xmlids.entries.get(xmlid)
        if record:
            found = _location(server, record.loc)
            if found:
                out.append(found)

    records = server.index.records
    for xmlid in records.by_model.get(model, []):
        action = records.actions.get(xmlid)
        rule = records.rules.get(xmlid)
        target = action.loc if action else (rule.loc if rule else None)
        found = _location(server, target)
        if found:
            out.append(found)

    for acl in server.index.security.acls_for_model(model):
        found = _location(server, acl.loc)
        if found:
            out.append(found)

    return out


def _field_references(server, model: str, field: str) -> list[types.Location]:
    out: list[types.Location] = []
    declaration = _location(server, server.resolver.fields(model).get(field))
    if declaration:
        out.append(declaration)

    compute = server.resolver.computes(model).get(field)
    if compute:
        found = _location(server, server.resolver.methods(model).get(compute))
        if found:
            out.append(found)

    return out


def _method_references(server, model: str, method: str) -> list[types.Location]:
    found = _location(server, server.resolver.methods(model).get(method))
    return [found] if found else []


def _component_references(server, name: str) -> list[types.Location]:
    out: list[types.Location] = []
    webx = server.index.webx
    component = webx.components.get(name) or webx.components.get(f"hx-{name}")
    if component:
        for loc in (component.vue_loc, component.js_loc):
            found = _location(server, loc)
            if found:
                out.append(found)
    for loc in webx.extensions.get(name, []) or []:
        found = _location(server, loc)
        if found:
            out.append(found)
    template = webx.templates.get(name)
    if template:
        found = _location(server, template)
        if found:
            out.append(found)
    return out


def _dedupe(locations: list[types.Location]) -> list[types.Location]:
    seen: set[tuple[str, int, int]] = set()
    out: list[types.Location] = []
    for item in locations:
        key = (item.uri, item.range.start.line, item.range.start.character)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def resolve_references(server, uri: str, position: types.Position) -> list[types.Location]:
    path = uri_to_path(uri)
    content = _read(server, uri)
    if not content:
        return []

    line = position.line + 1
    col = position.character
    model: str | None = None
    field: str | None = None
    method: str | None = None
    component: str | None = None

    if path.endswith(".xml"):
        ctx = resolve_xml_cursor(content, line, col, server.resolver)
        if ctx:
            if ctx.kind in ("field", "expr_field"):
                model, field = ctx.active_model, ctx.value.split(".")[0]
            elif ctx.kind == "method":
                model, method = ctx.active_model, ctx.value
            elif ctx.kind == "model":
                model = ctx.value
            elif ctx.kind in ("widget", "component"):
                component = ctx.value
    elif path.endswith(".py"):
        ctx = resolve_py_cursor(content, line, col, server.resolver)
        if ctx:
            if ctx.kind == "model":
                model = ctx.value
            elif ctx.kind == "dotted_field" and ctx.active_model:
                resolved = server.resolver.resolve_path(ctx.active_model, ctx.value)
                if resolved:
                    index = min(ctx.hop_index, len(resolved) - 1)
                    model, field = resolved[index][0], resolved[index][1]
            elif ctx.kind == "field":
                model, field = ctx.active_model, ctx.value
    elif path.endswith((".js", ".vue")):
        ctx = resolve_js_cursor(content, line, col)
        if ctx:
            if ctx.kind == "model":
                model = ctx.value
            elif ctx.kind == "method":
                model, method = ctx.secondary_value, ctx.value
            elif ctx.kind in ("component", "template", "widget"):
                component = ctx.value

    if component:
        return _dedupe(_component_references(server, component))
    if model and field:
        return _dedupe(_field_references(server, model, field))
    if model and method:
        return _dedupe(_method_references(server, model, method))
    if model:
        return _dedupe(_model_references(server, model))
    return []
