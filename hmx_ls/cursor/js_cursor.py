from __future__ import annotations

import re
from dataclasses import dataclass

RE_MODEL_KEY = re.compile(r"""\b(?:model|model_name|res_model)\s*:\s*(['\"])(.*?)\1""")
RE_METHOD_KEY = re.compile(r"""\bmethod\s*:\s*(['\"])(.*?)\1""")
RE_API_URL = re.compile(r"""(['\"])(/(?:hmx_api|web|mobile|portal|base)/[^'\"]*)\1""")
RE_VUE_TEMPLATE = re.compile(r"""VueTemplate\[\s*(['\"])(.*?)\1\s*\]""")
RE_COMPONENT_EXT = re.compile(r"""useComponentExtension\(\s*(['\"])(.*?)\1""")
RE_GET_COMPONENT = re.compile(r"""getComponent\(\s*(['\"])(.*?)\1""")
RE_DEFINE_STORE = re.compile(r"""defineStore\(\s*(['\"])(.*?)\1""")
RE_REGISTER_ACTION = re.compile(r"""registerAction\(\s*(['\"])(.*?)\1""")
RE_APP_COMPONENT = re.compile(r"""app\.component\(\s*(['\"])(.*?)\1""")
RE_TEMPLATE_NAME = re.compile(r"""<template\s+name=(['\"])(hx-[a-zA-Z0-9_-]+)\1""")
RE_HX_LITERAL = re.compile(r"""(['\"])(hx-[a-zA-Z0-9_-]+)\1""")
RE_FIELD_REGISTER = re.compile(
    r"""(?:List)?FieldRegistry\.register\(\s*(['\"])(.*?)\1\s*,\s*(['\"])(.*?)\3"""
)


@dataclass
class JsCursorContext:
    kind: str
    value: str
    secondary_value: str | None = None
    range: tuple[tuple[int, int], tuple[int, int]] | None = None


def _model_on_line(line: str) -> str | None:
    match = RE_MODEL_KEY.search(line)
    if match:
        return match.group(2).split(".")[-1].lower()
    return None


def _hit(line: str, col: int, pattern: re.Pattern, group: int) -> re.Match | None:
    for match in pattern.finditer(line):
        if match.start(group) <= col <= match.end(group):
            return match
    return None


def resolve_js_cursor(content: str, line: int, col: int) -> JsCursorContext | None:
    lines = content.splitlines()
    if line < 1 or line > len(lines):
        return None
    text = lines[line - 1]

    def span(match: re.Match, group: int) -> tuple[tuple[int, int], tuple[int, int]]:
        return ((line, match.start(group)), (line, match.end(group)))

    match = _hit(text, col, RE_FIELD_REGISTER, 2)
    if match:
        return JsCursorContext(kind="widget", value=match.group(2),
                               secondary_value=match.group(4), range=span(match, 2))

    match = _hit(text, col, RE_FIELD_REGISTER, 4)
    if match:
        return JsCursorContext(kind="component", value=match.group(4), range=span(match, 4))

    match = _hit(text, col, RE_MODEL_KEY, 2)
    if match:
        return JsCursorContext(kind="model", value=match.group(2).split(".")[-1].lower(),
                               range=span(match, 2))

    match = _hit(text, col, RE_METHOD_KEY, 2)
    if match:
        return JsCursorContext(kind="method", value=match.group(2),
                               secondary_value=_model_on_line(text), range=span(match, 2))

    match = _hit(text, col, RE_VUE_TEMPLATE, 2)
    if match:
        return JsCursorContext(kind="template", value=match.group(2), range=span(match, 2))

    match = _hit(text, col, RE_DEFINE_STORE, 2)
    if match:
        return JsCursorContext(kind="store", value=match.group(2), range=span(match, 2))

    match = _hit(text, col, RE_REGISTER_ACTION, 2)
    if match:
        return JsCursorContext(kind="action", value=match.group(2), range=span(match, 2))

    match = _hit(text, col, RE_APP_COMPONENT, 2)
    if match:
        return JsCursorContext(kind="component", value=match.group(2), range=span(match, 2))

    for pattern in (RE_COMPONENT_EXT, RE_GET_COMPONENT):
        match = _hit(text, col, pattern, 2)
        if match:
            return JsCursorContext(kind="component", value=match.group(2), range=span(match, 2))

    match = _hit(text, col, RE_API_URL, 2)
    if match:
        return JsCursorContext(kind="route", value=match.group(2), range=span(match, 2))

    match = _hit(text, col, RE_TEMPLATE_NAME, 2)
    if match:
        return JsCursorContext(kind="component", value=match.group(2), range=span(match, 2))

    match = _hit(text, col, RE_HX_LITERAL, 2)
    if match:
        return JsCursorContext(kind="component", value=match.group(2), range=span(match, 2))

    return None
