from __future__ import annotations

import os
from lsprotocol import types
from lxml import etree

from hmx_ls.cursor.common import loc_to_range, path_to_uri, uri_to_path


def resolve_document_symbols(server, uri: str) -> list[types.DocumentSymbol]:
    path = uri_to_path(uri)
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return []

    if not path.endswith(".xml"):
        return []

    try:
        root = etree.fromstring(content.encode("utf-8"))
    except Exception:
        return []

    symbols: list[types.DocumentSymbol] = []
    for elem in root.iter():
        tag = elem.tag
        if not isinstance(tag, str):
            continue
        line = getattr(elem, "sourceline", 1) - 1
        rng = types.Range(
            start=types.Position(line=max(0, line), character=0),
            end=types.Position(line=max(0, line), character=80),
        )
        if tag == "record":
            rid = elem.get("id", "<record>")
            model = elem.get("model", "")
            children: list[types.DocumentSymbol] = []
            for child in elem:
                if isinstance(child.tag, str) and child.tag == "field":
                    fname = child.get("name", "")
                    fline = getattr(child, "sourceline", 1) - 1
                    frng = types.Range(
                        start=types.Position(line=max(0, fline), character=0),
                        end=types.Position(line=max(0, fline), character=80),
                    )
                    children.append(types.DocumentSymbol(
                        name=f"field: {fname}",
                        kind=types.SymbolKind.Field,
                        range=frng,
                        selection_range=frng,
                    ))
            symbols.append(types.DocumentSymbol(
                name=f"{rid} ({model})",
                kind=types.SymbolKind.Class,
                range=rng,
                selection_range=rng,
                children=children,
            ))
        elif tag == "menuitem":
            mid = elem.get("id", "<menuitem>")
            mname = elem.get("name", "")
            symbols.append(types.DocumentSymbol(
                name=f"menu: {mid} - {mname}" if mname else f"menu: {mid}",
                kind=types.SymbolKind.Interface,
                range=rng,
                selection_range=rng,
            ))

    return symbols


def resolve_workspace_symbols(server, query: str) -> list[types.WorkspaceSymbol]:
    q = query.lower().strip()
    root = server.root
    results: list[types.WorkspaceSymbol] = []

    for m_name, entry in server.index.models.items():
        if not q or q in m_name:
            loc = entry.sites[0] if entry.sites else None
            if loc:
                results.append(types.WorkspaceSymbol(
                    name=m_name,
                    kind=types.SymbolKind.Class,
                    location=types.Location(uri=path_to_uri(loc.path, root), range=loc_to_range(loc)),
                    container_name="Model",
                ))
            if len(results) >= 100:
                return results

    for xid, entry in server.index.xmlids.entries.items():
        if not q or q in xid.lower():
            results.append(types.WorkspaceSymbol(
                name=xid,
                kind=types.SymbolKind.Variable,
                location=types.Location(uri=path_to_uri(entry.loc.path, root), range=loc_to_range(entry.loc)),
                container_name=entry.model or "XMLID",
            ))
            if len(results) >= 100:
                return results

    for w_name, entry in server.index.webx.widgets.items():
        if not q or q in w_name.lower():
            results.append(types.WorkspaceSymbol(
                name=w_name,
                kind=types.SymbolKind.Property,
                location=types.Location(uri=path_to_uri(entry.loc.path, root), range=loc_to_range(entry.loc)),
                container_name=f"Widget ({entry.component_name})",
            ))
            if len(results) >= 100:
                return results

    for (verb, path), entry in server.index.routes.routes.items():
        if not q or q in path.lower():
            results.append(types.WorkspaceSymbol(
                name=f"{verb} {path}",
                kind=types.SymbolKind.Function,
                location=types.Location(uri=path_to_uri(entry.loc.path, root), range=loc_to_range(entry.loc)),
                container_name="Route",
            ))
            if len(results) >= 100:
                return results

    return results
