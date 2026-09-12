from __future__ import annotations

import os
import re
from bisect import bisect_right
from dataclasses import dataclass, field

from .locations import Loc

STYLE_EXTS = (".css", ".scss")

RE_NOISE = re.compile(
    r"/\*.*?\*/"
    r"|\"(?:\\.|[^\"\\\n])*\""
    r"|'(?:\\.|[^'\\\n])*'"
    r"|(?<!:)//[^\n]*",
    re.S,
)
RE_DELIM = re.compile(r"[{};]")
RE_CLASS = re.compile(r"(?<![0-9.])\.([A-Za-z_-][A-Za-z0-9_-]*)")


@dataclass
class StyleEntry:
    name: str
    loc: Loc


@dataclass
class StyleIndex:
    classes: dict[str, list[StyleEntry]] = field(default_factory=dict)
    by_file: dict[str, list[str]] = field(default_factory=dict)

    def declarations(self, name: str) -> list[StyleEntry]:
        if not name:
            return []
        return self.classes.get(name, [])

    def prefixed(self, prefix: str, limit: int = 50) -> list[str]:
        if limit <= 0:
            return []
        names = [n for n in self.classes if n.startswith(prefix)]
        names.sort()
        return names[:limit]


def _blank(match: re.Match[str]) -> str:
    text = match.group()
    if "\n" not in text:
        return " " * len(text)
    return "\n".join(" " * len(part) for part in text.split("\n"))


def _line_starts(text: str) -> list[int]:
    starts = [0]
    idx = text.find("\n")
    while idx != -1:
        starts.append(idx + 1)
        idx = text.find("\n", idx + 1)
    return starts


def _selector_hits(text: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    start = 0
    for delim in RE_DELIM.finditer(text):
        if delim.group() == "{":
            prelude = text[start:delim.start()]
            if "." in prelude and not prelude.lstrip().startswith("@"):
                for m in RE_CLASS.finditer(prelude):
                    hits.append((start + m.start(1), m.group(1)))
        start = delim.end()
    return hits


def extract_styles(content: str, rel_path: str) -> list[StyleEntry]:
    text = RE_NOISE.sub(_blank, content)
    hits = _selector_hits(text)
    if not hits:
        return []
    starts = _line_starts(text)
    entries: list[StyleEntry] = []
    for offset, name in hits:
        row = bisect_right(starts, offset) - 1
        col = offset - starts[row]
        entries.append(
            StyleEntry(name, Loc(rel_path, row + 1, col, row + 1, col + len(name)))
        )
    return entries


def extract_styles_from_file(path: str, rel_path: str) -> list[StyleEntry]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return []
    return extract_styles(content, rel_path)


def scan_styles(root: str) -> StyleIndex:
    idx = StyleIndex()
    module_dir = os.path.join(root, "hmx", "module")
    if not os.path.isdir(module_dir):
        return idx

    for dirpath, _, filenames in os.walk(module_dir):
        if any(s in dirpath for s in (".git", "node_modules", "__pycache__")):
            continue
        for f in filenames:
            if not f.endswith(STYLE_EXTS):
                continue
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, root)
            entries = extract_styles_from_file(path, rel)
            if not entries:
                continue
            names: list[str] = []
            seen: set[str] = set()
            for entry in entries:
                idx.classes.setdefault(entry.name, []).append(entry)
                if entry.name not in seen:
                    seen.add(entry.name)
                    names.append(entry.name)
            idx.by_file[rel] = names

    return idx
