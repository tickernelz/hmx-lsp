from __future__ import annotations

import os
import re
from lsprotocol import types
from lxml import etree

from hmx_ls.cursor.common import uri_to_path

SEMANTIC_LEGEND = types.SemanticTokensLegend(
    token_types=["class", "property", "method", "variable", "function", "keyword"],
    token_modifiers=["declaration", "readonly", "deprecated", "defaultLibrary"],
)

TOKEN_CLASS = 0
TOKEN_PROPERTY = 1
TOKEN_METHOD = 2
TOKEN_VARIABLE = 3
TOKEN_FUNCTION = 4
TOKEN_KEYWORD = 5
MOD_NONE = 0
MOD_DECLARATION = 1

ATTR_RE = re.compile(r'([a-zA-Z0-9_:.-]+)\s*=\s*(["\'])(.*?)\2')
MODEL_ATTRS = ("model", "res_model", "binding_model")
XMLID_ATTRS = ("ref", "action", "inherit", "parent", "binding")
MODEL_TEXT_FIELDS = {"model", "res_model", "binding_model", "model_id"}
DECLARING_TAGS = {"record", "menuitem", "template"}
TAG_SPAN = 12


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

    def text(self, line: int, value: str) -> tuple[int, int] | None:
        needle = ">" + value
        for idx in range(max(0, line - 1), min(len(self.lines), line - 1 + TAG_SPAN)):
            start = self.lines[idx].find(needle)
            if start < 0:
                continue
            key = (idx, start + 1)
            if key in self.used:
                continue
            self.used.add(key)
            return idx, start + 1
        return None


def resolve_semantic_tokens(server, uri: str) -> types.SemanticTokens:
    path = uri_to_path(uri)
    doc = server.workspace.get_text_document(uri)
    content = doc.source if doc else ""
    if not content and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return types.SemanticTokens(data=[])

    if not content or not path.endswith(".xml"):
        return types.SemanticTokens(data=[])

    lines = content.splitlines()
    try:
        root = etree.fromstring(content.encode("utf-8"))
    except (etree.XMLSyntaxError, ValueError):
        return types.SemanticTokens(data=_encode(_fallback_tokens(lines)))
    return types.SemanticTokens(data=_encode(_tree_tokens(root, lines)))


def _tree_tokens(root, lines: list[str]) -> list[tuple[int, int, int, int, int]]:
    locator = _AttrLocator(lines)
    out: list[tuple[int, int, int, int, int]] = []
    for elem in root.iter():
        tag = elem.tag
        if not isinstance(tag, str):
            continue
        line = elem.sourceline or 1

        raw_id = elem.get("id")
        if raw_id and tag in DECLARING_TAGS:
            _push(out, locator.attr(line, "id", raw_id), raw_id, TOKEN_KEYWORD, MOD_DECLARATION)

        for attr in MODEL_ATTRS:
            value = elem.get(attr)
            if value:
                _push(out, locator.attr(line, attr, value), value, TOKEN_CLASS, MOD_NONE)

        for attr in XMLID_ATTRS:
            value = elem.get(attr)
            if value:
                _push(out, locator.attr(line, attr, value), value, TOKEN_KEYWORD, MOD_NONE)

        widget = elem.get("widget")
        if widget:
            _push(out, locator.attr(line, "widget", widget), widget, TOKEN_VARIABLE, MOD_NONE)

        groups = elem.get("groups")
        if groups:
            _push_groups(out, locator.attr(line, "groups", groups), groups)

        name = elem.get("name")
        if not name:
            continue
        if tag == "button":
            kind = TOKEN_KEYWORD if elem.get("type") == "action" else TOKEN_METHOD
            _push(out, locator.attr(line, "name", name), name, kind, MOD_NONE)
        elif tag == "field":
            _push(out, locator.attr(line, "name", name), name, TOKEN_PROPERTY, MOD_NONE)
            if name in MODEL_TEXT_FIELDS:
                target = (elem.text or "").strip()
                if target:
                    _push(out, locator.text(line, target), target, TOKEN_CLASS, MOD_NONE)
    return out


def _fallback_tokens(lines: list[str]) -> list[tuple[int, int, int, int, int]]:
    out: list[tuple[int, int, int, int, int]] = []
    for idx, text in enumerate(lines):
        for match in ATTR_RE.finditer(text):
            attr = match.group(1)
            value = match.group(3)
            if not value:
                continue
            spot = (idx, match.start(3))
            if attr in MODEL_ATTRS:
                _push(out, spot, value, TOKEN_CLASS, MOD_NONE)
            elif attr in XMLID_ATTRS:
                _push(out, spot, value, TOKEN_KEYWORD, MOD_NONE)
            elif attr == "widget":
                _push(out, spot, value, TOKEN_VARIABLE, MOD_NONE)
            elif attr == "groups":
                _push_groups(out, spot, value)
            elif attr == "name":
                head = text[:match.start(1)]
                if head.rfind("<button") > head.rfind("<field"):
                    _push(out, spot, value, TOKEN_METHOD, MOD_NONE)
                elif "<field" in head:
                    _push(out, spot, value, TOKEN_PROPERTY, MOD_NONE)
    return out


def _push(out: list, spot: tuple[int, int] | None, value: str, ttype: int, mods: int) -> None:
    if spot is None or not value:
        return
    out.append((spot[0], spot[1], len(value), ttype, mods))


def _push_groups(out: list, spot: tuple[int, int] | None, value: str) -> None:
    if spot is None:
        return
    cursor = 0
    for part in value.split(","):
        stripped = part.strip()
        if not stripped:
            cursor += len(part) + 1
            continue
        offset = value.find(stripped, cursor)
        if offset < 0:
            continue
        out.append((spot[0], spot[1] + offset, len(stripped), TOKEN_KEYWORD, MOD_NONE))
        cursor = offset + len(stripped)


def _encode(tokens: list[tuple[int, int, int, int, int]]) -> list[int]:
    data: list[int] = []
    prev_line = 0
    prev_char = 0
    for line, char, length, ttype, mods in sorted(set(tokens)):
        if length <= 0 or line < 0 or char < 0:
            continue
        delta_line = line - prev_line
        if delta_line < 0:
            continue
        delta_char = char - prev_char if delta_line == 0 else char
        if delta_char < 0:
            continue
        data += [delta_line, delta_char, length, ttype, mods]
        prev_line = line
        prev_char = char
    return data
