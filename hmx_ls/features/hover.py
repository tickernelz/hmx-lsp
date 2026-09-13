from __future__ import annotations

import os

from lsprotocol import types

from hmx_core.manifest import owner_of
from hmx_ls.cursor.common import safe_relpath, uri_to_path
from hmx_ls.cursor.js_cursor import resolve_js_cursor
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor

DECORATOR_DOCS = {
    "api.model": "### `@api.model`\nMethod operates on the model itself; `self` carries no active record ids.",
    "api.depends": "### `@api.depends(*paths)`\nDeclares the fields a computed field depends on. Dotted paths traverse relations.",
    "api.onchange": "### `@api.onchange(*fields)`\nRuns in the form view when the listed fields change, before the record is saved.",
    "api.constrains": "### `@api.constrains(*fields)`\nPython validation invoked on create and write. Raise `ValidationError` to reject.",
    "api.model_create_multi": "### `@api.model_create_multi`\nReceives a list of value dictionaries and creates every record in one batch.",
    "api.transition": "### `@api.transition(field, from_state, to_state)`\nGuards a state-machine transition on the named status field.",
    "api.depends_context": "### `@api.depends_context(*keys)`\nRecomputes when the listed context keys change.",
    "api.returns": "### `@api.returns(model)`\nCoerces the return value into a recordset of the named model.",
}


def _markdown(lines: list[str]) -> types.Hover:
    return types.Hover(contents=types.MarkupContent(
        kind=types.MarkupKind.Markdown, value="\n".join(lines)))


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


def _field_card(server, model: str, name: str, prefix: str = "Field") -> types.Hover | None:
    entry = server.index.models.get(model)
    fields = server.resolver.fields(model)
    if name not in fields:
        return None
    lines = [f"### {prefix} `{name}`", "", f"- **Model**: `{model}`"]
    kind = server.resolver.field_kind(model, name)
    if kind:
        lines.append(f"- **Type**: `{kind}`")
    comodel = server.resolver.comodel(model, name)
    if comodel:
        lines.append(f"- **Relates to**: `{comodel}`")
    choices = server.resolver.selections(model).get(name)
    if choices:
        shown = ", ".join(f"`{c}`" for c in choices[:8])
        more = "" if len(choices) <= 8 else f" (+{len(choices) - 8} more)"
        lines.append(f"- **Choices**: {shown}{more}")
    compute = server.resolver.computes(model).get(name)
    if compute:
        lines.append(f"- **Computed by**: `{compute}()`")
    if entry:
        origin = ("injected" if name in entry.injected
                  else "reverse relation" if name in entry.reverse else "declared")
        lines.append(f"- **Origin**: {origin}")
    loc = fields.get(name)
    if loc:
        lines.append(f"- **Declared at**: `{loc}`")
    return _markdown(lines)


def _model_card(server, model: str) -> types.Hover | None:
    if not server.resolver.known(model):
        return None
    entry = server.index.models.get(model)
    fields = server.resolver.fields(model)
    methods = server.resolver.methods(model)
    lines = [f"### Model `{model}`", "",
             f"- **Fields**: {len(fields)}", f"- **Methods**: {len(methods)}"]
    if entry and entry.edges:
        lines.append(f"- **Inherits**: {', '.join('`' + e + '`' for e in sorted(entry.edges))}")
    if entry and entry.rec_name:
        lines.append(f"- **Display field**: `{entry.rec_name}`")
    if entry and entry.ordering:
        lines.append(f"- **Default order**: `{', '.join(entry.ordering)}`")
    views = server.index.xmlids.models.get(model, [])
    if views:
        lines.append(f"- **Views**: {len(views)}")
    rules = server.index.records.rules_for_model(model)
    if rules:
        lines.append(f"- **Record rules**: {len(rules)}")
    acls = server.index.security.acls_for_model(model)
    if acls:
        lines.append(f"- **ACL rows**: {len(acls)}")
    if entry and entry.sites:
        lines.append(f"- **Declared in**: {len(entry.sites)} file(s)")
    return _markdown(lines)


def _method_card(server, model: str, name: str) -> types.Hover | None:
    loc = server.resolver.methods(model).get(name)
    if loc is None:
        return None
    return _markdown([f"### Method `{name}()`", "",
                      f"- **Model**: `{model}`", f"- **Defined at**: `{loc}`"])


def _widget_card(server, value: str) -> types.Hover | None:
    widget, component = server.index.webx.resolve_widget(value)
    if widget is None and component is None:
        return None
    lines = [f"### Widget `{value}`", ""]
    if widget:
        lines.append(f"- **Registry**: `{widget.registry_type}`")
        lines.append(f"- **Component**: `{widget.component_name}`")
        lines.append(f"- **Registered at**: `{widget.loc}`")
    if component:
        if component.vue_loc:
            lines.append(f"- **Template**: `{component.vue_loc}`")
        if component.js_loc:
            lines.append(f"- **Script**: `{component.js_loc}`")
    return _markdown(lines)


def _xmlid_card(server, value: str, module: str | None) -> types.Hover | None:
    records = server.index.records
    action = records.action(value, module)
    if action:
        lines = [f"### Action `{action.xmlid}`", "", f"- **Kind**: `{action.kind}`"]
        if action.res_model:
            lines.append(f"- **Model**: `{action.res_model}`")
        if action.tag:
            lines.append(f"- **Client tag**: `{action.tag}`")
        if action.view_mode:
            lines.append(f"- **View modes**: `{action.view_mode}`")
        if action.domain:
            lines.append(f"- **Domain**: `{action.domain}`")
        lines.append(f"- **Declared at**: `{action.loc}`")
        return _markdown(lines)

    group = records.group(value, module)
    if group:
        lines = [f"### Security group `{group.xmlid}`", ""]
        if group.name:
            lines.append(f"- **Name**: {group.name}")
        if group.implied:
            lines.append(f"- **Implies**: {', '.join('`' + i + '`' for i in group.implied)}")
        acls = server.index.security.acls_for_group(group.xmlid)
        if acls:
            lines.append(f"- **ACL rows**: {len(acls)}")
        lines.append(f"- **Declared at**: `{group.loc}`")
        return _markdown(lines)

    menu = records.menu(value, module)
    if menu:
        lines = [f"### Menu `{menu.xmlid}`", ""]
        if menu.name:
            lines.append(f"- **Label**: {menu.name}")
        if menu.parent:
            lines.append(f"- **Parent**: `{menu.parent}`")
        if menu.action:
            lines.append(f"- **Action**: `{menu.action}`")
        if menu.groups:
            lines.append(f"- **Groups**: {', '.join('`' + g + '`' for g in menu.groups)}")
        lines.append(f"- **Declared at**: `{menu.loc}`")
        return _markdown(lines)

    entry = server.index.xmlids.get(value, module)
    if entry:
        lines = [f"### Record `{entry.xmlid}`", ""]
        if entry.model:
            lines.append(f"- **Model**: `{entry.model}`")
        if entry.name:
            lines.append(f"- **Name**: {entry.name}")
        lines.append(f"- **Declared at**: `{entry.loc}`")
        return _markdown(lines)
    return None


def _route_card(server, value: str) -> types.Hover | None:
    route = server.index.routes.get("ANY", value)
    if route is None:
        return None
    lines = [f"### Route `{route.path}`", "", f"- **Verb**: `{route.verb}`"]
    if route.handler_name:
        lines.append(f"- **Handler**: `{route.handler_name}()`")
    if route.module:
        lines.append(f"- **Module**: `{route.module}`")
    lines.append(f"- **Declared at**: `{route.loc}`")
    return _markdown(lines)


def _component_card(server, value: str) -> types.Hover | None:
    webx = server.index.webx
    component = webx.components.get(value) or webx.components.get(f"hx-{value}")
    if component is None:
        loc = webx.templates.get(value)
        if loc is None:
            return _widget_card(server, value)
        return _markdown([f"### Template `{value}`", "", f"- **Declared at**: `{loc}`"])
    lines = [f"### Component `{component.name}`", ""]
    if component.vue_loc:
        lines.append(f"- **Template**: `{component.vue_loc}`")
    if component.js_loc:
        lines.append(f"- **Script**: `{component.js_loc}`")
    extensions = webx.extensions.get(component.name) or []
    if extensions:
        lines.append(f"- **Extended by**: {len(extensions)} call site(s)")
    return _markdown(lines)


def _from_xml(server, content: str, line: int, col: int, module: str | None) -> types.Hover | None:
    ctx = resolve_xml_cursor(content, line, col, server.resolver)
    if ctx is None:
        return None

    if ctx.kind in ("field", "expr_field") and ctx.active_model:
        head = ctx.value.split(".")[0]
        prefix = "Field" if ctx.kind == "field" else f"`{ctx.attribute}` field"
        return _field_card(server, ctx.active_model, head, prefix)
    if ctx.kind == "method" and ctx.active_model:
        return _method_card(server, ctx.active_model, ctx.value)
    if ctx.kind == "model":
        return _model_card(server, ctx.value)
    if ctx.kind == "widget":
        return _widget_card(server, ctx.value)
    if ctx.kind == "component":
        return _component_card(server, ctx.value)
    if ctx.kind == "xmlid":
        return _xmlid_card(server, ctx.value, module)
    if ctx.kind == "selection":
        return _markdown([f"### Selection value `{ctx.value}`", "",
                          f"- **Attribute**: `{ctx.attribute}`"])
    return None


def _from_python(server, content: str, line: int, col: int, module: str | None) -> types.Hover | None:
    ctx = resolve_py_cursor(content, line, col, server.resolver)
    if ctx is None:
        return None

    if ctx.kind == "decorator":
        doc = DECORATOR_DOCS.get(ctx.value)
        return _markdown([doc]) if doc else None
    if ctx.kind == "model":
        return _model_card(server, ctx.value)
    if ctx.kind == "xmlid":
        return _xmlid_card(server, ctx.value, module)
    if ctx.kind == "dotted_field" and ctx.active_model:
        resolved = server.resolver.resolve_path(ctx.active_model, ctx.value)
        if not resolved:
            return None
        index = min(ctx.hop_index, len(resolved) - 1)
        owner, hop, _ = resolved[index]
        label = f"`{ctx.secondary_value}` field" if ctx.secondary_value else "Field"
        return _field_card(server, owner, hop, label)
    if ctx.kind == "field" and ctx.active_model:
        return _field_card(server, ctx.active_model, ctx.value)
    return None


def _from_js(server, content: str, line: int, col: int) -> types.Hover | None:
    ctx = resolve_js_cursor(content, line, col)
    if ctx is None:
        return None

    if ctx.kind == "model":
        return _model_card(server, ctx.value)
    if ctx.kind == "method" and ctx.secondary_value:
        return _method_card(server, ctx.secondary_value, ctx.value)
    if ctx.kind == "route":
        return _route_card(server, ctx.value)
    if ctx.kind in ("component", "template"):
        return _component_card(server, ctx.value)
    if ctx.kind == "widget":
        return _widget_card(server, ctx.value)
    if ctx.kind == "store":
        entry = server.index.webx.stores.get(ctx.value)
        if entry is None:
            return None
        return _markdown([f"### Pinia store `{entry.name}`", "", f"- **Defined at**: `{entry.loc}`"])
    return None


def resolve_hover(server, uri: str, position: types.Position) -> types.Hover | None:
    path = uri_to_path(uri)
    content = _read(server, uri)
    if not content:
        return None

    module = owner_of(safe_relpath(path, server.root))
    line = position.line + 1
    col = position.character

    if path.endswith(".xml"):
        return _from_xml(server, content, line, col, module)
    if path.endswith(".py"):
        return _from_python(server, content, line, col, module)
    if path.endswith((".js", ".vue")):
        return _from_js(server, content, line, col)
    return None
