from __future__ import annotations

import os
from lsprotocol import types
from lxml import etree

from hmx_core.manifest import owner_of
from hmx_core.security import normalize_model_id
from hmx_ls.cursor.common import loc_to_range, path_to_uri, uri_to_path
from hmx_ls.cursor.js_cursor import resolve_js_cursor
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor


def resolve_definition(server, uri: str, position: types.Position) -> list[types.Location]:
    path = uri_to_path(uri)
    root = server.root
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return []

    line = position.line + 1
    col = position.character
    rel_path = os.path.relpath(path, root) if root else path
    current_module = owner_of(rel_path)

    if path.endswith(".xml"):
        ctx = resolve_xml_cursor(content, line, col, server.resolver)
        if not ctx:
            return []
        if ctx.kind == "xpath" and ctx.inherit_ref:
            parent_entry = server.index.xmlids.get(ctx.inherit_ref, current_module)
            if parent_entry:
                parent_path = os.path.join(root, parent_entry.loc.path) if root else parent_entry.loc.path
                try:
                    ptree = etree.parse(parent_path)
                    raw_pid = ctx.inherit_ref.split(".")[-1]
                    target_rec = None
                    for rec in ptree.iter("record"):
                        if rec.get("id") == raw_pid:
                            target_rec = rec
                            break
                    if target_rec is not None:
                        for f in target_rec:
                            if f.tag == "field" and f.get("name") == "arch":
                                matches = f.xpath(ctx.value)
                                if matches and getattr(matches[0], "sourceline", None):
                                    m_line = matches[0].sourceline - 1
                                    return [types.Location(
                                        uri=path_to_uri(parent_entry.loc.path, root),
                                        range=types.Range(
                                            start=types.Position(line=m_line, character=0),
                                            end=types.Position(line=m_line, character=40),
                                        ),
                                    )]
                except Exception:
                    pass
                return [types.Location(uri=path_to_uri(parent_entry.loc.path, root), range=loc_to_range(parent_entry.loc))]

        elif ctx.kind == "field" and ctx.active_model:
            fields = server.resolver.fields(ctx.active_model)
            loc = fields.get(ctx.value)
            if loc and loc.path != "<framework>":
                return [types.Location(uri=path_to_uri(loc.path, root), range=loc_to_range(loc))]
        elif ctx.kind == "model":
            entry = server.index.models.get(ctx.value)
            if entry and entry.sites:
                return [types.Location(uri=path_to_uri(s.path, root), range=loc_to_range(s)) for s in entry.sites]
        elif ctx.kind == "widget":
            w_entry, c_entry = server.index.webx.resolve_widget(ctx.value)
            target = (c_entry.vue_loc or c_entry.js_loc) if c_entry else (w_entry.loc if w_entry else None)
            if target:
                return [types.Location(uri=path_to_uri(target.path, root), range=loc_to_range(target))]
        elif ctx.kind == "xmlid":
            entry = server.index.xmlids.get(ctx.value, current_module)
            if entry:
                return [types.Location(uri=path_to_uri(entry.loc.path, root), range=loc_to_range(entry.loc))]

    elif path.endswith(".py"):
        ctx = resolve_py_cursor(content, line, col)
        if not ctx:
            return []
        if ctx.kind == "model":
            entry = server.index.models.get(ctx.value)
            if entry and entry.sites:
                return [types.Location(uri=path_to_uri(s.path, root), range=loc_to_range(s)) for s in entry.sites]
        elif ctx.kind == "dotted_field" and ctx.active_model:
            hops = ctx.value.split(".")
            curr = ctx.active_model
            target_loc = None
            for idx in range(ctx.hop_index + 1):
                hop_name = hops[idx]
                fields = server.resolver.fields(curr)
                target_loc = fields.get(hop_name)
                if idx < ctx.hop_index:
                    curr = server.resolver.comodel(curr, hop_name)
                    if not curr:
                        break
            if target_loc and target_loc.path != "<framework>":
                return [types.Location(uri=path_to_uri(target_loc.path, root), range=loc_to_range(target_loc))]
        elif ctx.kind == "xmlid":
            entry = server.index.xmlids.get(ctx.value, current_module)
            if entry:
                return [types.Location(uri=path_to_uri(entry.loc.path, root), range=loc_to_range(entry.loc))]

    elif path.endswith(".js") or path.endswith(".vue"):
        ctx = resolve_js_cursor(content, line, col)
        if ctx:
            if ctx.kind == "model":
                entry = server.index.models.get(ctx.value)
                if entry and entry.sites:
                    return [types.Location(uri=path_to_uri(s.path, root), range=loc_to_range(s)) for s in entry.sites]
            elif ctx.kind == "method" and ctx.secondary_value:
                methods = server.resolver.methods(ctx.secondary_value)
                loc = methods.get(ctx.value)
                if loc:
                    return [types.Location(uri=path_to_uri(loc.path, root), range=loc_to_range(loc))]
            elif ctx.kind == "route":
                route = server.index.routes.get("ANY", ctx.value)
                if route:
                    return [types.Location(uri=path_to_uri(route.loc.path, root), range=loc_to_range(route.loc))]
            elif ctx.kind == "component":
                comp = server.index.webx.components.get(ctx.value)
                if comp:
                    target = comp.vue_loc or comp.js_loc
                    if target:
                        return [types.Location(uri=path_to_uri(target.path, root), range=loc_to_range(target))]

    elif path.endswith(".csv"):
        lines = content.splitlines()
        if 0 <= position.line < len(lines):
            row_text = lines[position.line]
            cols = [c.strip() for c in row_text.split(",")]
            for token in cols:
                if token.startswith("model_"):
                    norm = normalize_model_id(token)
                    entry = server.index.models.get(norm)
                    if entry and entry.sites:
                        return [types.Location(uri=path_to_uri(s.path, root), range=loc_to_range(s)) for s in entry.sites]
                elif "." in token:
                    entry = server.index.xmlids.get(token, current_module)
                    if entry:
                        return [types.Location(uri=path_to_uri(entry.loc.path, root), range=loc_to_range(entry.loc))]

    return []
