from __future__ import annotations

import os
from lsprotocol import types

from hmx_ls.cursor.common import loc_to_range, path_to_uri, uri_to_path
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor


def resolve_references(server, uri: str, position: types.Position) -> list[types.Location]:
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
    target_model: str | None = None
    target_field: str | None = None

    if path.endswith(".xml"):
        ctx = resolve_xml_cursor(content, line, col, server.resolver)
        if ctx:
            if ctx.kind == "field" and ctx.active_model:
                target_model = ctx.active_model
                target_field = ctx.value
            elif ctx.kind == "model":
                target_model = ctx.value
    elif path.endswith(".py"):
        ctx = resolve_py_cursor(content, line, col)
        if ctx:
            if ctx.kind == "model":
                target_model = ctx.value
            elif ctx.kind == "dotted_field" and ctx.active_model:
                target_model = ctx.active_model
                target_field = ctx.value.split(".")[ctx.hop_index]

    if not target_model and not target_field:
        return []

    results: list[types.Location] = []

    if target_model and not target_field:
        entry = server.index.models.get(target_model)
        if entry:
            for s in entry.sites:
                results.append(types.Location(uri=path_to_uri(s.path, root), range=loc_to_range(s)))
        for xmlid in server.index.xmlids.models.get(target_model, []):
            xentry = server.index.xmlids.entries.get(xmlid)
            if xentry:
                results.append(types.Location(uri=path_to_uri(xentry.loc.path, root), range=loc_to_range(xentry.loc)))
        for acl in server.index.security.acls_for_model(target_model):
            results.append(types.Location(uri=path_to_uri(acl.loc.path, root), range=loc_to_range(acl.loc)))

    elif target_model and target_field:
        fields = server.resolver.fields(target_model)
        loc = fields.get(target_field)
        if loc and loc.path != "<framework>":
            results.append(types.Location(uri=path_to_uri(loc.path, root), range=loc_to_range(loc)))

    return results
