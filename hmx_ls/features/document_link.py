from __future__ import annotations

import ast
import csv
import os
import re
from lsprotocol import types

from hmx_core.manifest import owner_of
from hmx_core.security import normalize_model_id
from hmx_ls.cursor.common import path_to_uri, uri_to_path
from hmx_ls.cursor.js_cursor import RE_API_URL

RE_XML_REF = re.compile(r"""(ref|inherit|action)\s*=\s*(['"])([^'"]+)\2""")
RE_XML_WIDGET = re.compile(r"""widget\s*=\s*(['"])([^'"]+)\1""")
RE_XML_MODEL = re.compile(r"""model\s*=\s*(['"])([^'"]+)\1""")


def resolve_document_links(server, uri: str) -> list[types.DocumentLink]:
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

    rel_path = os.path.relpath(path, root) if root else path
    current_module = owner_of(rel_path)
    links: list[types.DocumentLink] = []

    if path.endswith(".xml"):
        for line_idx, line_str in enumerate(content.splitlines()):
            for m in RE_XML_REF.finditer(line_str):
                ref_val = m.group(3)
                entry = server.index.xmlids.get(ref_val, current_module)
                if entry:
                    target_uri = path_to_uri(entry.loc.path, root)
                    links.append(types.DocumentLink(
                        range=types.Range(
                            start=types.Position(line=line_idx, character=m.start(3)),
                            end=types.Position(line=line_idx, character=m.end(3)),
                        ),
                        target=target_uri,
                        tooltip=f"Jump to {ref_val}",
                    ))

            for m in RE_XML_WIDGET.finditer(line_str):
                w_val = m.group(2)
                w_entry, c_entry = server.index.webx.resolve_widget(w_val)
                target_loc = (c_entry.vue_loc or c_entry.js_loc) if c_entry else (w_entry.loc if w_entry else None)
                if target_loc:
                    links.append(types.DocumentLink(
                        range=types.Range(
                            start=types.Position(line=line_idx, character=m.start(2)),
                            end=types.Position(line=line_idx, character=m.end(2)),
                        ),
                        target=path_to_uri(target_loc.path, root),
                        tooltip=f"Open Webx widget {w_val}",
                    ))

            for m in RE_XML_MODEL.finditer(line_str):
                m_val = m.group(2)
                entry = server.index.models.get(m_val)
                if entry and entry.sites:
                    links.append(types.DocumentLink(
                        range=types.Range(
                            start=types.Position(line=line_idx, character=m.start(2)),
                            end=types.Position(line=line_idx, character=m.end(2)),
                        ),
                        target=path_to_uri(entry.sites[0].path, root),
                        tooltip=f"Open model {m_val}",
                    ))

    elif path.endswith(".js"):
        for line_idx, line_str in enumerate(content.splitlines()):
            for m in RE_API_URL.finditer(line_str):
                url_val = m.group(2)
                route = server.index.routes.get("ANY", url_val)
                if route:
                    links.append(types.DocumentLink(
                        range=types.Range(
                            start=types.Position(line=line_idx, character=m.start(2)),
                            end=types.Position(line=line_idx, character=m.end(2)),
                        ),
                        target=path_to_uri(route.loc.path, root),
                        tooltip=f"API handler for {url_val}",
                    ))

    elif path.endswith(".csv"):
        for line_idx, line_str in enumerate(content.splitlines()):
            for token in line_str.split(","):
                token = token.strip()
                if token.startswith("model_"):
                    norm = normalize_model_id(token)
                    entry = server.index.models.get(norm)
                    if entry and entry.sites:
                        idx = line_str.find(token)
                        links.append(types.DocumentLink(
                            range=types.Range(
                                start=types.Position(line=line_idx, character=idx),
                                end=types.Position(line=line_idx, character=idx + len(token)),
                            ),
                            target=path_to_uri(entry.sites[0].path, root),
                            tooltip=f"Open model {norm}",
                        ))
                elif "." in token:
                    entry = server.index.xmlids.get(token, current_module)
                    if entry:
                        idx = line_str.find(token)
                        links.append(types.DocumentLink(
                            range=types.Range(
                                start=types.Position(line=line_idx, character=idx),
                                end=types.Position(line=line_idx, character=idx + len(token)),
                            ),
                            target=path_to_uri(entry.loc.path, root),
                            tooltip=f"Open XMLID {token}",
                        ))

    return links
