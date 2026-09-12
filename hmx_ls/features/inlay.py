from __future__ import annotations

import os
import re
from lsprotocol import types
from lxml import etree

from hmx_ls.cursor.common import uri_to_path

VIEW_MODEL = "baseuiview"
SUBVIEW_TAGS = {"list", "form", "search", "kanban", "pivot", "graph", "calendar",
                "activity", "gantt", "hierarchy", "quick", "tree"}
ATTR_RE = re.compile(r'([a-zA-Z0-9_:.-]+)\s*=\s*(["\'])(.*?)\2')
MAX_HINTS = 200
TAG_SPAN = 12
MAX_DEPTH = 8


class _AttrLocator:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.used: set[tuple[int, int]] = set()

    def attr(self, line: int, name: str, value: str) -> tuple[int, int] | None:
        for idx in range(max(0, line - 1), min(len(self.lines), line - 1 + TAG_SPAN)):
            for match in ATTR_RE.finditer(self.lines[idx]):
                if match.group(1) != name or match.group(3) != value:
                    continue
                key = (idx, match.start(3))
                if key in self.used:
                    continue
                self.used.add(key)
                return idx, match.start(3)
        return None


def resolve_inlay_hints(server, uri: str, rng: types.Range) -> list[types.InlayHint]:
    path = uri_to_path(uri)
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return []

    if not content or not path.endswith(".xml"):
        return []
    try:
        root = etree.fromstring(content.encode("utf-8"))
    except (etree.XMLSyntaxError, ValueError):
        return []

    lines = content.splitlines()
    locator = _AttrLocator(lines)
    low = rng.start.line if rng is not None else 0
    high = rng.end.line if rng is not None else len(lines)
    hints: list[types.InlayHint] = []

    for record in root.iter("record"):
        if record.get("model") != VIEW_MODEL:
            continue
        fields = _record_fields(record)
        model = _value(fields.get("model"))
        arch = fields.get("arch")
        if not model or arch is None or not _known(server, model):
            continue
        _walk(server, arch, model, locator, low, high, hints, 0)
        if len(hints) >= MAX_HINTS:
            break
    return hints[:MAX_HINTS]


def _record_fields(record) -> dict[str, object]:
    return {child.get("name"): child for child in record
            if isinstance(child.tag, str) and child.tag == "field" and child.get("name")}


def _value(node) -> str | None:
    if node is None:
        return None
    ref = node.get("ref")
    if ref:
        return ref
    text = (node.text or "").strip()
    return text or None


def _walk(server, node, model: str, locator: _AttrLocator, low: int, high: int,
          hints: list[types.InlayHint], depth: int) -> None:
    if depth > MAX_DEPTH:
        return
    for child in node:
        if not isinstance(child.tag, str):
            continue
        if child.tag != "field":
            _walk(server, child, model, locator, low, high, hints, depth)
            continue
        name = child.get("name")
        if not name:
            continue
        base = name.split(".")[0]
        target = _comodel(server, model, base)
        if len(hints) < MAX_HINTS:
            label = _label(server, model, base, target)
            if label:
                spot = locator.attr(child.sourceline or 1, "name", name)
                if spot is not None and low <= spot[0] <= high:
                    hints.append(types.InlayHint(
                        position=types.Position(line=spot[0],
                                                character=spot[1] + len(name) + 1),
                        label=label,
                        kind=types.InlayHintKind.Type,
                        padding_left=True,
                    ))
        if not target or not _known(server, target):
            continue
        if any(isinstance(sub.tag, str) and sub.tag in SUBVIEW_TAGS for sub in child):
            _walk(server, child, target, locator, low, high, hints, depth + 1)


def _label(server, model: str, name: str, target: str | None) -> str | None:
    if target:
        return f": {target}"
    kind = _kind(server, model, name, frozenset())
    return f": {kind}" if kind else None


def _known(server, model: str | None) -> bool:
    if not model:
        return False
    try:
        return bool(server.resolver.known(model))
    except Exception:
        return False


def _comodel(server, model: str, name: str) -> str | None:
    try:
        got = server.resolver.comodel(model, name)
    except Exception:
        return None
    return got if isinstance(got, str) and got else None


def _kind(server, model: str, name: str, seen: frozenset[str]) -> str | None:
    if model in seen or len(seen) > MAX_DEPTH:
        return None
    try:
        entry = server.index.models.get(model)
    except Exception:
        return None
    if entry is None:
        return None
    kinds = getattr(entry, "kinds", None)
    if isinstance(kinds, dict):
        got = kinds.get(name)
        if isinstance(got, str) and got:
            return got
    edges = getattr(entry, "edges", None)
    if not edges:
        return None
    for parent in sorted(edges):
        found = _kind(server, parent, name, seen | {model})
        if found:
            return found
    return None
