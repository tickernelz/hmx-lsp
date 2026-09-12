from __future__ import annotations

import re
from dataclasses import dataclass

RE_CALL_KW_MODEL = re.compile(r"""model\s*:\s*(['"])(.*?)\1""")
RE_CALL_KW_METHOD = re.compile(r"""method\s*:\s*(['"])(.*?)\1""")
RE_API_URL = re.compile(r"""(['"])(\/(?:hmx_api|api|web)\/[^'"]+)\1""")
RE_HX_TAG = re.compile(r"""(['"])(hx-[a-zA-Z0-9_-]+)\1""")
RE_VUE_TEMPLATE = re.compile(r"""<template\s+name=(['"])(hx-[a-zA-Z0-9_-]+)\1""")


@dataclass
class JsCursorContext:
    kind: str
    value: str
    secondary_value: str | None = None
    range: tuple[tuple[int, int], tuple[int, int]] | None = None


def resolve_js_cursor(content: str, line: int, col: int) -> JsCursorContext | None:
    lines = content.splitlines()
    if line < 1 or line > len(lines):
        return None
    target_line = lines[line - 1]

    for m in RE_CALL_KW_MODEL.finditer(target_line):
        if m.start(2) <= col <= m.end(2):
            return JsCursorContext(kind="model", value=m.group(2).lower(),
                                   range=((line, m.start(2)), (line, m.end(2))))

    for m in RE_CALL_KW_METHOD.finditer(target_line):
        if m.start(2) <= col <= m.end(2):
            model_name = None
            for mm in RE_CALL_KW_MODEL.finditer(target_line):
                model_name = mm.group(2).lower()
                break
            return JsCursorContext(kind="method", value=m.group(2),
                                   secondary_value=model_name,
                                   range=((line, m.start(2)), (line, m.end(2))))

    for m in RE_API_URL.finditer(target_line):
        if m.start(2) <= col <= m.end(2):
            return JsCursorContext(kind="route", value=m.group(2),
                                   range=((line, m.start(2)), (line, m.end(2))))

    for m in RE_VUE_TEMPLATE.finditer(target_line):
        if m.start(2) <= col <= m.end(2):
            return JsCursorContext(kind="component", value=m.group(2),
                                   range=((line, m.start(2)), (line, m.end(2))))

    for m in RE_HX_TAG.finditer(target_line):
        if m.start(2) <= col <= m.end(2):
            return JsCursorContext(kind="component", value=m.group(2),
                                   range=((line, m.start(2)), (line, m.end(2))))

    return None
