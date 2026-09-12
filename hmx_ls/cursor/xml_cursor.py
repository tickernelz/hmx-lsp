from __future__ import annotations

import re
from dataclasses import dataclass
from lxml import etree

from hmx_core.resolve import Resolver

SUBVIEW_TAGS = {"list", "form", "search", "kanban", "pivot", "graph", "calendar",
                "activity", "gantt", "hierarchy", "quick", "tree"}


@dataclass
class XmlCursorContext:
    kind: str
    value: str
    active_model: str | None = None
    attribute: str | None = None
    tag: str | None = None
    inherit_ref: str | None = None
    range: tuple[tuple[int, int], tuple[int, int]] | None = None


def resolve_xml_cursor(content: str, line: int, col: int,
                       resolver: Resolver | None = None) -> XmlCursorContext | None:
    lines = content.splitlines()
    if line < 1 or line > len(lines):
        return None
    target_line = lines[line - 1]

    attr_name: str | None = None
    attr_val: str | None = None
    rng: tuple[tuple[int, int], tuple[int, int]] | None = None

    pat = re.compile(r'([a-zA-Z0-9_:-]+)\s*=\s*(["\'])(.*?)\2')
    for m in pat.finditer(target_line):
        start_val = m.start(3)
        end_val = m.end(3)
        if start_val <= col <= end_val:
            attr_name = m.group(1)
            attr_val = m.group(3)
            rng = ((line, start_val), (line, end_val))
            break

    try:
        root = etree.fromstring(content.encode("utf-8"))
    except Exception:
        if attr_name and attr_val:
            kind = "field" if attr_name == "name" else ("widget" if attr_name == "widget" else "xmlid")
            return XmlCursorContext(kind=kind, value=attr_val, attribute=attr_name, range=rng)
        return None

    target_elem = None
    for elem in root.iter():
        if getattr(elem, "sourceline", None) == line:
            target_elem = elem
            break

    root_model = None
    inherit_ref = None
    elem_cursor = target_elem
    while elem_cursor is not None:
        if elem_cursor.tag == "record":
            for child in elem_cursor:
                if isinstance(child.tag, str) and child.tag == "field":
                    fname = child.get("name")
                    if fname == "model":
                        text = (child.text or "").strip()
                        if text:
                            root_model = text
                    elif fname == "inherit":
                        ref = child.get("ref") or (child.text or "").strip()
                        if ref:
                            inherit_ref = ref
            if root_model or inherit_ref:
                break
        elem_cursor = elem_cursor.getparent()

    active_model = root_model
    if resolver and root_model and target_elem is not None:
        chain: list[str] = []
        p = target_elem.getparent()
        while p is not None and p.tag != "record":
            if p.tag == "field" and p.get("name") and p.get("name") != "arch" and any(c.tag in SUBVIEW_TAGS for c in p):
                chain.append(p.get("name"))
            p = p.getparent()
        curr = root_model
        for field_name in reversed(chain):
            target = resolver.comodel(curr, field_name.split(".")[0])
            if target and resolver.known(target):
                curr = target
            else:
                break
        active_model = curr

    tag = target_elem.tag if target_elem is not None else None
    if not attr_name and target_elem is not None and target_elem.text:
        text = target_elem.text.strip()
        if target_elem.tag == "field" and target_elem.get("name") == "model":
            return XmlCursorContext(kind="model", value=text, active_model=text,
                                    attribute="model", tag=tag, inherit_ref=inherit_ref)

    if tag == "xpath" and (attr_name == "expr" or not attr_name):
        expr_val = attr_val or (target_elem.get("expr") if target_elem is not None else "")
        return XmlCursorContext(kind="xpath", value=expr_val or "", active_model=active_model,
                                attribute=attr_name or "expr", tag=tag,
                                inherit_ref=inherit_ref, range=rng)

    if attr_name == "name" and tag == "field":
        return XmlCursorContext(kind="field", value=attr_val or "", active_model=active_model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit_ref, range=rng)
    if attr_name == "model" and tag == "record":
        return XmlCursorContext(kind="model", value=attr_val or "", active_model=attr_val,
                                attribute=attr_name, tag=tag, inherit_ref=inherit_ref, range=rng)
    if attr_name == "widget":
        return XmlCursorContext(kind="widget", value=attr_val or "", active_model=active_model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit_ref, range=rng)
    if attr_name in ("ref", "action", "inherit", "parent"):
        return XmlCursorContext(kind="xmlid", value=attr_val or "", active_model=active_model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit_ref, range=rng)

    if attr_name:
        return XmlCursorContext(kind="unknown", value=attr_val or "", active_model=active_model,
                                attribute=attr_name, tag=tag, inherit_ref=inherit_ref, range=rng)
    return None
