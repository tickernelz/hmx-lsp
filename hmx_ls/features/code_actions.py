from __future__ import annotations

import difflib
import re
from lsprotocol import types

from hmx_ls.cursor.common import path_to_uri, uri_to_path
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor


def resolve_code_actions(server, uri: str, rng: types.Range,
                         context: types.CodeActionContext) -> list[types.CodeAction]:
    actions: list[types.CodeAction] = []
    path = uri_to_path(uri)
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""

    for diag in context.diagnostics:
        if diag.code == "hmx-unknown-widget":
            w_match = re.search(r"Unknown widget '([^']+)'", diag.message)
            w_val = w_match.group(1) if w_match else ""
            if not w_val:
                line = diag.range.start.line + 1
                col = diag.range.start.character
                ctx = resolve_xml_cursor(content, line, col, server.resolver)
                w_val = ctx.value if ctx else ""

            if w_val:
                candidates = difflib.get_close_matches(w_val, server.index.webx.widgets.keys(), n=3, cutoff=0.4)
                if not candidates:
                    candidates = ["statinfo", "many2many_tags", "statusbar", "boolean_toggle"]
                for cand in candidates[:3]:
                    edit = types.WorkspaceEdit(
                        changes={
                            uri: [
                                types.TextEdit(
                                    range=diag.range,
                                    new_text=f'widget="{cand}"',
                                )
                            ]
                        }
                    )
                    actions.append(types.CodeAction(
                        title=f"Replace with known widget '{cand}'",
                        kind=types.CodeActionKind.QuickFix,
                        diagnostics=[diag],
                        edit=edit,
                        is_preferred=True,
                    ))

        elif diag.code == "hmx-unknown-field":
            f_match = re.search(r"Unknown field '([^']+)' on model '([^']+)'", diag.message)
            f_val = f_match.group(1) if f_match else ""
            m_val = f_match.group(2) if f_match else ""

            if not f_val or not m_val:
                line = diag.range.start.line + 1
                col = diag.range.start.character
                ctx = resolve_xml_cursor(content, line, col, server.resolver)
                if ctx:
                    f_val = ctx.value
                    m_val = ctx.active_model or ""

            if f_val and m_val:
                model_fields = server.resolver.fields(m_val)
                candidates = difflib.get_close_matches(f_val, model_fields.keys(), n=3, cutoff=0.4)
                for cand in candidates:
                    edit = types.WorkspaceEdit(
                        changes={
                            uri: [
                                types.TextEdit(
                                    range=diag.range,
                                    new_text=f'name="{cand}"',
                                )
                            ]
                        }
                    )
                    actions.append(types.CodeAction(
                        title=f"Did you mean field '{cand}'?",
                        kind=types.CodeActionKind.QuickFix,
                        diagnostics=[diag],
                        edit=edit,
                        is_preferred=True,
                    ))

                entry = server.index.models.get(m_val)
                if entry and entry.sites:
                    site = entry.sites[0]
                    site_uri = path_to_uri(site.path, server.root)
                    insert_line = site.line
                    actions.append(types.CodeAction(
                        title=f"Declare field '{f_val}' in {site.path}",
                        kind=types.CodeActionKind.QuickFix,
                        diagnostics=[diag],
                        edit=types.WorkspaceEdit(
                            changes={
                                site_uri: [
                                    types.TextEdit(
                                        range=types.Range(
                                            start=types.Position(line=insert_line, character=0),
                                            end=types.Position(line=insert_line, character=0),
                                        ),
                                        new_text=f"    {f_val} = models.CharField(max_length=255, blank=True)\n",
                                    )
                                ]
                            }
                        ),
                    ))

    return actions
