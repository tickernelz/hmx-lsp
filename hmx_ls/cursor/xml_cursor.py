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
    reference: bool = False


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


def _canonical_model(value: str | None) -> str | None:
    if not value:
        return None
    model = value.split(".")[-1].lower()
    return model[6:] if model.startswith("model_") else model


def _record_facts(record) -> tuple[str | None, str | None]:
    if record is None:
        return None, None
    record_model = (record.get("model") or "").split(".")[-1].lower() or None
    model = record_model
    inherit = None
    view_record = record_model in {"baseuiview", "ir.ui.view", "ui.view", "view"}
    for child in record:
        if not isinstance(child.tag, str) or child.tag != "field":
            continue
        name = child.get("name")
        if name == "inherit" and inherit is None:
            inherit = child.get("ref") or (child.text or "").strip() or None
        elif name == "model" and view_record:
            model = (_canonical_model(child.get("ref"))
                     if child.get("ref") else (child.text or "").strip().split(".")[-1].lower())
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


def _start_tag_spans(content: str, root):
    spans = []
    elements = [elem for elem in root.iter() if isinstance(elem.tag, str)]
    element_index = 0
    i = 0
    line = 1
    col = 0
    while i < len(content) and element_index < len(elements):
        if content[i] == "\n":
            line += 1
            col = 0
            i += 1
            continue
        if content[i] != "<" or i + 1 >= len(content) or content[i + 1] in "!?/":
            col += 1
            i += 1
            continue
        j = i + 1
        quote = None
        while j < len(content):
            char = content[j]
            if quote:
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == ">":
                break
            j += 1
        if j >= len(content):
            break
        elem = elements[element_index]
        spans.append((elem, line, col, j + 1))
        element_index += 1
        segment = content[i:j + 1]
        newlines = segment.count("\n")
        if newlines:
            line += newlines
            col = len(segment.rsplit("\n", 1)[1])
        else:
            col += len(segment)
        i = j + 1
    return spans


def _element_at(root, content: str, line: int, col: int):
    for elem, start_line, start_col, end_offset in _start_tag_spans(content, root):
        segment = content[:end_offset]
        end_line = segment.count("\n") + 1
        end_col = len(segment.rsplit("\n", 1)[-1])
        if (start_line, start_col) <= (line, col) <= (end_line, end_col):
            return elem
    return None


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


def _class_token_at(value: str, offset: int) -> tuple[str, int, int] | None:
    for match in re.finditer(r"[^\s]+", value):
        if match.start() <= offset <= match.end():
            return match.group(0), match.start(), match.end()
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

    elem = _element_at(root, content, line, col)
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

    if attr_name == "ref" and tag == "field" and elem.get("name") in MODEL_FIELDS:
        raw = attr_value or ""
        value = _canonical_model(raw) or raw
        return XmlCursorContext(kind="model", value=value, active_model=value,
                                attribute=elem.get("name"), tag=tag, inherit_ref=inherit,
                                range=span, reference=True)

    if attr_name == "name" and tag == "button":
        button_type = elem.get("type") if elem is not None else None
        value = attr_value or ""
        if button_type == "action" or value.startswith("%("):
            stripped = value[2:value.rfind(")")] if value.startswith("%(") else value
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

    if attr_name == "class" and attr_value is not None:
        token = _class_token_at(attr_value, col - value_start)
        if token is None:
            return None
        name, start, end = token
        return XmlCursorContext(kind="cssclass", value=name, active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit,
                                range=((line, value_start + start), (line, value_start + end)))

    if attr_name:
        return XmlCursorContext(kind="unknown", value=attr_value or "", active_model=model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit, range=span)
    return None
