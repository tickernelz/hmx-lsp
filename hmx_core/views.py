"""Reads baseuiview records and resolves arch field references."""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from .locations import Loc

VIEW_MODEL = "baseuiview"
SUBVIEW_TAGS = {"list", "form", "search", "kanban", "pivot", "graph", "calendar",
                "activity", "gantt", "hierarchy", "quick"}


@dataclass
class FieldRef:
    model: str
    name: str
    loc: Loc


def _record_fields(record) -> dict[str, object]:
    return {c.get("name"): c for c in record
            if isinstance(c.tag, str) and c.tag == "field" and c.get("name")}


def _value(node) -> str | None:
    if node is None:
        return None
    ref = node.get("ref")
    if ref:
        return ref
    text = (node.text or "").strip()
    return text or None


def collect(path: str, rel: str, resolver) -> tuple[list[FieldRef], int, int]:
    """Returns field references, view-record count, and records skipped as unknown model."""
    try:
        tree = etree.parse(path)
    except (etree.XMLSyntaxError, OSError):
        return [], 0, 0
    refs: list[FieldRef] = []
    records = skipped = 0

    def walk(node, current: str) -> None:
        for child in node:
            if not isinstance(child.tag, str):
                continue
            if child.tag != "field":
                walk(child, current)
                continue
            name = child.get("name")
            if not name:
                continue
            refs.append(FieldRef(current, name, Loc(rel, child.sourceline or 0)))
            if any(isinstance(g.tag, str) and g.tag in SUBVIEW_TAGS for g in child):
                target = resolver.comodel(current, name.split(".")[0])
                if target and resolver.known(target):
                    walk(child, target)

    for record in tree.iter("record"):
        if record.get("model") != VIEW_MODEL:
            continue
        records += 1
        fields = _record_fields(record)
        model = _value(fields.get("model"))
        arch = fields.get("arch")
        if not model or arch is None:
            continue
        if not resolver.known(model):
            skipped += 1
            continue
        walk(arch, model)
    return refs, records, skipped
