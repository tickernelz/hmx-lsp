from __future__ import annotations

import os
from lsprotocol import types
from lxml import etree

from hmx_ls.cursor.common import uri_to_path

FOLD_TAGS = {"record", "form", "list", "tree", "search", "kanban", "sheet",
             "notebook", "page", "group", "xpath", "template", "menuitem"}
ARCH_FIELDS = {"arch", "code", "domain_force"}


def resolve_folding_ranges(server, uri: str) -> list[types.FoldingRange]:
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

    out: list[types.FoldingRange] = []
    seen: set[tuple[int, int]] = set()
    for elem in root.iter():
        tag = elem.tag
        if not isinstance(tag, str):
            continue
        if tag == "field":
            if elem.get("name") not in ARCH_FIELDS:
                continue
        elif tag not in FOLD_TAGS:
            continue
        start = elem.sourceline or 0
        if start < 1:
            continue
        end = _end_line(elem)
        if end - start < 1:
            continue
        key = (start - 1, end - 1)
        if key in seen:
            continue
        seen.add(key)
        out.append(types.FoldingRange(start_line=key[0], end_line=key[1],
                                      kind=types.FoldingRangeKind.Region))
    return out


def _end_line(elem) -> int:
    start = elem.sourceline or 0
    last = 0
    for desc in elem.iterdescendants():
        if not isinstance(desc.tag, str):
            continue
        line = desc.sourceline or 0
        if line > last:
            last = line
    boundary = 0
    sibling = elem.getnext()
    if sibling is not None:
        sibling_line = sibling.sourceline or 0
        if sibling_line > start:
            boundary = sibling_line - 1
    if last and boundary:
        return max(last, boundary)
    return last or boundary or start
