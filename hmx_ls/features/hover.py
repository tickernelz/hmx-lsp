from __future__ import annotations

import os
from lsprotocol import types

from hmx_core.manifest import owner_of
from hmx_ls.cursor.common import uri_to_path
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor

DECORATOR_DOCS = {
    "api.model": """### `@api.model`
Decorates a method where `self` is a recordset acting at the model level (current environment, no active record IDs required).
- Commonly used for utility methods, domain searches, and server actions.""",
    "api.depends": """### `@api.depends(*fields)`
Compute method dependency declaration.
- Specifies which fields trigger recomputation when modified.
- Supports dotted relational paths (e.g. `@api.depends('partner_id.name')`).""",
    "api.onchange": """### `@api.onchange(*fields)`
Client-side field change trigger.
- Automatically invoked in the form view when the specified fields are edited by the user.
- Runs before saving to database; can update values or return warning dialogs.""",
    "api.constrains": """### `@api.constrains(*fields)`
Python validation constraint.
- Invoked on `create` and `write` to enforce business logic invariants.
- Must raise `ValidationError` if an invariant fails.""",
    "api.model_create_multi": """### `@api.model_create_multi`
Batch record creation optimization.
- The method receives a list of dictionary values rather than a single dict, creating all records in one batch.""",
    "api.transition": """### `@api.transition(field, state_from, state_to)`
State machine transition validator.
- Restricts and validates status changes for the specified state field.""",
    "api.depends_context": """### `@api.depends_context(*keys)`
Context-dependent compute declaration.
- Re-evaluates computed fields when context keys (e.g. `company`, `allowed_company_ids`, `uid`) change.""",
    "api.returns": """### `@api.returns(model, downgrade=None)`
Return type adapter.
- Ensures the returned recordset belongs to the specified model.""",
}


def resolve_hover(server, uri: str, position: types.Position) -> types.Hover | None:
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
    rel_path = os.path.relpath(path, root) if root else path

    if path.endswith(".xml"):
        ctx = resolve_xml_cursor(content, line, col, server.resolver)
        if not ctx:
            return None
        if ctx.kind == "field" and ctx.active_model:
            model = ctx.active_model
            fields = server.resolver.fields(model)
            loc = fields.get(ctx.value)
            entry = server.index.models.get(model)
            comodel = server.resolver.comodel(model, ctx.value)
            is_injected = ctx.value in entry.injected if entry else False
            is_reverse = ctx.value in entry.reverse if entry else False
            status = "injected" if is_injected else ("reverse" if is_reverse else "declared")

            md = [f"### Field `{ctx.value}`", "", f"- **Model**: `{model}`"]
            if comodel:
                md.append(f"- **Comodel Target**: `{comodel}`")
            md.append(f"- **Kind**: `{status}`")
            if loc:
                md.append(f"- **Declared At**: `{loc}`")
            return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value="\n".join(md)))

        elif ctx.kind == "model":
            model = ctx.value
            entry = server.index.models.get(model)
            field_count = len(server.resolver.fields(model)) if server.resolver else 0
            md = [f"### HMX Model `{model}`", "", f"- **Composed Fields**: {field_count}"]
            if entry and entry.edges:
                md.append(f"- **Inherits**: `{', '.join(sorted(entry.edges))}`")
            if entry and entry.sites:
                md.append(f"- **Declaration Sites**: {len(entry.sites)}")
            return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value="\n".join(md)))

        elif ctx.kind == "widget":
            w_entry, c_entry = server.index.webx.resolve_widget(ctx.value)
            md = [f"### Webx Widget `{ctx.value}`", ""]
            if w_entry:
                md.append(f"- **Registry**: `{w_entry.registry_type}`")
                md.append(f"- **Component**: `{w_entry.component_name}`")
            if c_entry:
                if c_entry.vue_loc:
                    md.append(f"- **Template**: `{c_entry.vue_loc}`")
                if c_entry.js_loc:
                    md.append(f"- **JS**: `{c_entry.js_loc}`")
            return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value="\n".join(md)))

        elif ctx.kind == "xmlid":
            mod = owner_of(rel_path)
            entry = server.index.xmlids.get(ctx.value, mod)
            if entry:
                md = [f"### XMLID `{entry.xmlid}`", ""]
                if entry.model:
                    md.append(f"- **Model**: `{entry.model}`")
                if entry.name:
                    md.append(f"- **Name**: {entry.name}")
                md.append(f"- **Location**: `{entry.loc}`")
                return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value="\n".join(md)))

    elif path.endswith(".py"):
        ctx = resolve_py_cursor(content, line, col)
        if not ctx:
            return None

        if ctx.kind == "decorator":
            doc_text = DECORATOR_DOCS.get(ctx.value)
            if doc_text:
                return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=doc_text))

        elif ctx.kind == "dotted_field" and ctx.active_model:
            hops = ctx.value.split(".")
            curr = ctx.active_model
            target_field = hops[ctx.hop_index]
            for idx in range(ctx.hop_index):
                curr = server.resolver.comodel(curr, hops[idx])
                if not curr:
                    break

            if curr:
                fields = server.resolver.fields(curr)
                loc = fields.get(target_field)
                comodel = server.resolver.comodel(curr, target_field)
                dec_name = ctx.secondary_value or "field"
                md = [f"### Parameter in `{dec_name}`: `{target_field}`", "",
                      f"- **Model**: `{curr}`"]
                if comodel:
                    md.append(f"- **Comodel Target**: `{comodel}`")
                if loc:
                    md.append(f"- **Declared At**: `{loc}`")
                return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value="\n".join(md)))

        elif ctx.kind == "model":
            model = ctx.value
            entry = server.index.models.get(model)
            field_count = len(server.resolver.fields(model)) if server.resolver else 0
            md = [f"### HMX Model `{model}`", "", f"- **Composed Fields**: {field_count}"]
            if entry and entry.edges:
                md.append(f"- **Inherits**: `{', '.join(sorted(entry.edges))}`")
            return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value="\n".join(md)))

        elif ctx.kind == "xmlid":
            mod = owner_of(rel_path)
            entry = server.index.xmlids.get(ctx.value, mod)
            if entry:
                md = [f"### XMLID `{entry.xmlid}`", "", f"- **Model**: `{entry.model or 'unknown'}`",
                      f"- **Location**: `{entry.loc}`"]
                return types.Hover(contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value="\n".join(md)))

    return None
