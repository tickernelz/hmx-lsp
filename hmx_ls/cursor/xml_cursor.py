from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import etree

from hmx_core.expressions import refs_for_attribute
from hmx_core.resolve import Resolver

SUBVIEW_TAGS = {"list", "form", "search", "kanban", "pivot", "graph", "calendar",
                "activity", "gantt", "hierarchy", "quick", "tree"}
XMLID_ATTRS = {"ref", "action", "inherit", "parent", "binding"}
MODEL_FIELDS = {"model", "res_model", "binding_model", "model_id"}
EXPR_ATTRS = {"domain", "attrs", "context", "options", "default_order", "order",
              "invisible", "readonly", "required", "column_invisible", "eval",
              "groups", "on_change", "onchange", "states", "statusbar_visible"}
ATTR_PATTERN = re.compile(r"([a-zA-Z0-9_:.-]+)\s*=\s*([\"'])(.*?)\2", re.DOTALL)


@dataclass
class XmlCursorContext:
    kind: str
    value: str
    active_model: str | None = None
    attribute: str | None = None
    tag: str | None = None
    inherit_ref: str | None = None
    range: tuple[tuple[int, int], tuple[int, int]] | None = None


def _attribute_at(line_text: str, line: int, col: int) -> tuple[str, str, tuple, int] | None:
    for match in ATTR_PATTERN.finditer(line_text):
        start, end = match.start(3), match.end(3)
        if start <= col <= end:
            span = ((line, start), (line, end))
            return match.group(1), match.group(3), span, start
    return None


def _record_of(elem):
    cursor = elem
    while cursor is not None:
        if cursor.tag == "record":
            return cursor
        cursor = cursor.getparent()
    return None


def _record_facts(record) -> tuple[str | None, str | None]:
    if record is None:
        return None, None
    model = None
    inherit = None
    for child in record:
        if not isinstance(child.tag, str) or child.tag != "field":
            continue
        name = child.get("name")
        if name in MODEL_FIELDS and model is None:
            model = child.get("ref") or (child.text or "").strip() or None
        elif name == "inherit" and inherit is None:
            inherit = child.get("ref") or (child.text or "").strip() or None
    if model:
        model = model.split(".")[-1].lower()
    return model, inherit


def _active_model(elem, root_model: str | None, resolver: Resolver | None) -> str | None:
    if not resolver or not root_model or elem is None:
        return root_model
    chain: list[str] = []
    parent = elem.getparent()
    while parent is not None and parent.tag != "record":
        name = parent.get("name") if isinstance(parent.tag, str) else None
        if (parent.tag == "field" and name and name != "arch"
                and any(isinstance(c.tag, str) and c.tag in SUBVIEW_TAGS for c in parent)):
            chain.append(name)
        parent = parent.getparent()
    current = root_model
    for name in reversed(chain):
        target = resolver.comodel(current, name.split(".")[0])
        if target and resolver.known(target):
            current = target
        else:
            break
    return current


def _element_at(root, line: int):
    best = None
    for elem in root.iter():
        if not isinstance(elem.tag, str):
            continue
        if getattr(elem, "sourceline", None) == line:
            best = elem
            break
    return best


def _expression_context(attr: str, value: str, col: int, value_start: int,
                        line: int, model: str | None, tag: str | None,
                        inherit: str | None) -> XmlCursorContext | None:
    offset = col - value_start
    for ref in refs_for_attribute(attr, value):
        if ref.start <= offset <= ref.end:
            span = ((line, value_start + ref.start), (line, value_start + ref.end))
            kind = {"field": "expr_field", "xmlid": "xmlid",
                    "method": "method", "value": "selection"}.get(ref.kind, "unknown")
            return XmlCursorContext(kind=kind, value=ref.path, active_model=model,
                                    attribute=attr, tag=tag, inherit_ref=inherit, range=span)
    return None


def resolve_xml_cursor(content: str, line: int, col: int,
                       resolver: Resolver | None = None) -> XmlCursorContext | None:
    lines = content.splitlines()
    if line < 1 or line > len(lines):
        return None

    found = _attribute_at(lines[line - 1], line, col)
    attr_name = found[0] if found else None
    attr_value = found[1] if found else None
    span = found[2] if found else None
    value_start = found[3] if found else 0

    try:
        root = etree.fromstring(content.encode("utf-8"))
    except Exception:
        if attr_name and attr_value is not None:
            if attr_name in EXPR_ATTRS:
                ctx = _expression_context(attr_name, attr_value, col, value_start,
                                          line, None, None, None)
                if ctx:
                    return ctx
            kind = "field" if attr_name == "name" else (
                "widget" if attr_name == "widget" else
                "xmlid" if attr_name in XMLID_ATTRS else "unknown")
            return XmlCursorContext(kind=kind, value=attr_value,
                                    attribute=attr_name, range=span)
        return None

    elem = _element_at(root, line)
    tag = elem.tag if elem is not None else None
    record = _record_of(elem) if elem is not None else None
    root_model, inherit = _record_facts(record)
    model = _active_model(elem, root_model, resolver)

    if attr_name in EXPR_ATTRS and attr_value is not None:
        ctx = _expression_context(attr_name, attr_value, col, value_start,
                                  line, model, tag, inherit)
        if ctx:
            return ctx

    if attr_name is None and elem is not None:
        text = (elem.text or "").strip()
        if elem.tag == "field" and elem.get("name") in MODEL_FIELDS and text:
            normalized = text.split(".")[-1].lower()
            return XmlCursorContext(kind="model", value=normalized, active_model=normalized,
                                    attribute=elem.get("name"), tag=tag, inherit_ref=inherit)
        return None

    if attr_name == "name" and tag == "field":
        return XmlCursorContext(kind="field", value=attr_value or "", active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)

    if attr_name == "name" and tag == "button":
        button_type = elem.get("type") if elem is not None else None
        value = attr_value or ""
        if button_type == "action" or value.startswith("%("):
            stripped = value[2:].rstrip(")ds") if value.startswith("%(") else value
            return XmlCursorContext(kind="xmlid", value=stripped, active_model=model,
                                    attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)
        return XmlCursorContext(kind="method", value=value, active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)

    if attr_name in MODEL_FIELDS and attr_value:
        normalized = attr_value.split(".")[-1].lower()
        if tag == "record" and attr_name == "model":
            return XmlCursorContext(kind="model", value=normalized, active_model=normalized,
                                    attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)
        return XmlCursorContext(kind="model", value=normalized, active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)

    if attr_name == "widget":
        return XmlCursorContext(kind="widget", value=attr_value or "", active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)

    if tag == "xpath" and attr_name == "expr":
        return XmlCursorContext(kind="xpath", value=attr_value or "", active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)

    if attr_name in XMLID_ATTRS and attr_value:
        return XmlCursorContext(kind="xmlid", value=attr_value, active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)

    if attr_name == "tag" and tag == "field":
        return XmlCursorContext(kind="component", value=attr_value or "", active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)

    if attr_name:
        return XmlCursorContext(kind="unknown", value=attr_value or "", active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)
    return None
