from __future__ import annotations

import os

from lsprotocol import types
from lxml import etree

from hmx_core.manifest import owner_of
from hmx_core.security import normalize_model_id
from hmx_ls.cursor.common import loc_to_range, path_to_uri, safe_relpath, uri_to_path
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


def _at(server, loc) -> list[types.Location]:
    if loc is None or loc.path == "<framework>":
        return []
    return [types.Location(uri=path_to_uri(loc.path, server.root), range=loc_to_range(loc))]


def _model_sites(server, model: str | None) -> list[types.Location]:
    if not model:
        return []
    entry = server.index.models.get(model)
    if not entry or not entry.sites:
        return []
    return [types.Location(uri=path_to_uri(s.path, server.root), range=loc_to_range(s))
            for s in entry.sites]


def _style_locations(server, name: str) -> list[types.Location]:
    index = getattr(server, "styles", None)
    if index is None:
        return []
    out: list[types.Location] = []
    for entry in index.declarations(name):
        out.append(types.Location(
            uri=path_to_uri(os.path.join(server.root, entry.loc.path)),
            range=loc_to_range(entry.loc),
        ))
    return out


def _xmlid(server, value: str, module: str | None) -> list[types.Location]:
    entry = server.index.xmlids.get(value, module)
    if entry:
        return _at(server, entry.loc)
    records = server.index.records
    for accessor in (records.action, records.group, records.menu):
        found = accessor(value, module)
        if found:
            return _at(server, found.loc)
    rule = records.rules.get(value)
    if rule:
        return _at(server, rule.loc)
    return []


def _widget(server, value: str) -> list[types.Location]:
    widget, component = server.index.webx.resolve_widget(value)
    target = None
    if component:
        target = component.vue_loc or component.js_loc
    if target is None and widget:
        target = widget.loc
    return _at(server, target)


def _component(server, value: str) -> list[types.Location]:
    webx = server.index.webx
    component = webx.components.get(value) or webx.components.get(f"hx-{value}")
    if component:
        target = component.vue_loc or component.js_loc
        if target:
            return _at(server, target)
    loc = webx.templates.get(value)
    if loc:
        return _at(server, loc)
    return _widget(server, value)


def _route(server, value: str) -> list[types.Location]:
    route = server.index.routes.get("ANY", value)
    if route:
        return _at(server, route.loc)
    return []


def _path_hop(server, model: str | None, dotted: str, hop: int) -> list[types.Location]:
    if not model:
        return []
    resolved = server.resolver.resolve_path(model, dotted)
    if not resolved:
        return []
    index = min(hop, len(resolved) - 1)
    return _at(server, resolved[index][2])


def _xpath_target(server, ctx, module: str | None) -> list[types.Location]:
    parent = server.index.xmlids.get(ctx.inherit_ref, module) if ctx.inherit_ref else None
    if parent is None:
        return []
    parent_path = os.path.join(server.root, parent.loc.path) if server.root else parent.loc.path
    try:
        tree = etree.parse(parent_path)
    except (OSError, etree.XMLSyntaxError):
        return _at(server, parent.loc)

    raw_id = ctx.inherit_ref.split(".")[-1]
    for record in tree.iter("record"):
        if record.get("id") != raw_id:
            continue
        for child in record:
            if not isinstance(child.tag, str) or child.get("name") != "arch":
                continue
            try:
                matches = child.xpath(ctx.value)
            except (etree.XPathError, ValueError):
                matches = []
            line = getattr(matches[0], "sourceline", None) if matches else None
            if line:
                return [types.Location(
                    uri=path_to_uri(parent.loc.path, server.root),
                    range=types.Range(
                        start=types.Position(line=line - 1, character=0),
                        end=types.Position(line=line - 1, character=80),
                    ),
                )]
    return _at(server, parent.loc)


def _from_xml(server, content: str, line: int, col: int, module: str | None) -> list[types.Location]:
    ctx = resolve_xml_cursor(content, line, col, server.resolver)
    if ctx is None:
        return []

    if ctx.kind == "cssclass":
        return _style_locations(server, ctx.value)

    if ctx.kind == "xpath":
        return _xpath_target(server, ctx, module)
    if ctx.kind in ("field", "expr_field"):
        if not ctx.active_model:
            return []
        if "." in ctx.value:
            return _path_hop(server, ctx.active_model, ctx.value, ctx.value.count("."))
        return _at(server, server.resolver.fields(ctx.active_model).get(ctx.value))
    if ctx.kind == "method":
        if not ctx.active_model:
            return []
        return _at(server, server.resolver.methods(ctx.active_model).get(ctx.value))
    if ctx.kind == "model":
        return _model_sites(server, ctx.value)
    if ctx.kind == "widget":
        return _widget(server, ctx.value)
    if ctx.kind == "component":
        return _component(server, ctx.value)
    if ctx.kind == "xmlid":
        return _xmlid(server, ctx.value, module)
    if ctx.kind == "selection" and ctx.active_model:
        return _at(server, server.resolver.fields(ctx.active_model).get("state"))
    return []


def _from_python(server, content: str, line: int, col: int, module: str | None) -> list[types.Location]:
    ctx = resolve_py_cursor(content, line, col)
    if ctx is None:
        return []

    if ctx.kind == "model":
        return _model_sites(server, ctx.value)
    if ctx.kind == "xmlid":
        return _xmlid(server, ctx.value, module)
    if ctx.kind == "dotted_field" and ctx.active_model:
        return _path_hop(server, ctx.active_model, ctx.value, ctx.hop_index)
    if ctx.kind == "field" and ctx.active_model:
        return _at(server, server.resolver.fields(ctx.active_model).get(ctx.value))
    if ctx.kind == "method" and ctx.active_model:
        return _at(server, server.resolver.methods(ctx.active_model).get(ctx.value))
    return []


def _from_js(server, content: str, line: int, col: int) -> list[types.Location]:
    ctx = resolve_js_cursor(content, line, col)
    if ctx is None:
        return []

    if ctx.kind == "model":
        return _model_sites(server, ctx.value)
    if ctx.kind == "method" and ctx.secondary_value:
        return _at(server, server.resolver.methods(ctx.secondary_value).get(ctx.value))
    if ctx.kind == "route":
        return _route(server, ctx.value)
    if ctx.kind in ("component", "template"):
        return _component(server, ctx.value)
    if ctx.kind == "widget":
        return _widget(server, ctx.value)
    if ctx.kind == "store":
        entry = server.index.webx.stores.get(ctx.value)
        return _at(server, entry.loc) if entry else []
    if ctx.kind == "action":
        return _at(server, server.index.webx.actions.get(ctx.value))
    return []


def _from_csv(server, content: str, zero_line: int, module: str | None) -> list[types.Location]:
    lines = content.splitlines()
    if not 0 <= zero_line < len(lines):
        return []
    for token in (c.strip() for c in lines[zero_line].split(",")):
        if not token:
            continue
        if token.startswith("model_") or ".model_" in token:
            hit = _model_sites(server, normalize_model_id(token))
            if hit:
                return hit
        elif "." in token:
            hit = _xmlid(server, token, module)
            if hit:
                return hit
    return []


def resolve_definition(server, uri: str, position: types.Position) -> list[types.Location]:
    path = uri_to_path(uri)
    content = _read(server, uri)
    if not content:
        return []

    module = owner_of(safe_relpath(path, server.root))
    line = position.line + 1
    col = position.character

    if path.endswith(".xml"):
        return _from_xml(server, content, line, col, module)
    if path.endswith(".py"):
        return _from_python(server, content, line, col, module)
    if path.endswith((".js", ".vue")):
        return _from_js(server, content, line, col)
    if path.endswith(".csv"):
        return _from_csv(server, content, position.line, module)
    return []
