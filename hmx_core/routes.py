from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .locations import Loc
from .manifest import owner_of

RE_NINJA_ROUTE = re.compile(
    r"""@(api|router|api_router)\.(get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]"""
)
RE_DJANGO_PATH = re.compile(
    r"""path\(\s*['"]([^'"]+)['"]\s*,\s*([a-zA-Z0-9_.]+)"""
)


@dataclass
class RouteEntry:
    verb: str
    path: str
    handler_name: str
    loc: Loc
    module: str | None = None


@dataclass
class RoutesIndex:
    routes: dict[tuple[str, str], RouteEntry] = field(default_factory=dict)
    by_path: dict[str, list[RouteEntry]] = field(default_factory=dict)
    by_file: dict[str, list[tuple[str, str]]] = field(default_factory=dict)

    def get(self, verb: str, path: str) -> RouteEntry | None:
        v = verb.upper()
        norm_path = normalize_path(path)
        exact = self.routes.get((v, norm_path))
        if exact is not None:
            return exact
        matches = self.by_path.get(norm_path)
        if matches:
            for r in matches:
                if r.verb == v:
                    return r
            return matches[0]
        return self._prefix_match(v, norm_path)

    def _prefix_match(self, verb: str, path: str) -> RouteEntry | None:
        for (v, p), entry in self.routes.items():
            if v != verb:
                continue
            if "{" in p:
                pattern = re.sub(r"\{[^}]+\}", "[^/]+", p)
                if re.fullmatch(pattern, path):
                    return entry
            elif path.startswith(p.rstrip("/") + "/"):
                return entry
        return None


def normalize_path(p: str) -> str:
    cleaned = p.strip()
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return cleaned.rstrip("/") if len(cleaned) > 1 else cleaned


def extract_routes_from_py(path: str, rel_path: str, module: str | None) -> list[RouteEntry]:
    routes: list[RouteEntry] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return routes

    lines = content.splitlines()
    for m in RE_NINJA_ROUTE.finditer(content):
        verb = m.group(2).upper()
        raw_path = m.group(3)
        norm = normalize_path(raw_path)
        line_num = content[:m.start()].count("\n") + 1
        fn_name = ""
        for i in range(line_num, min(line_num + 5, len(lines))):
            curr = lines[i].strip()
            if curr.startswith("def ") or curr.startswith("async def "):
                fn_name = curr.split("(")[0].replace("async def ", "").replace("def ", "").strip()
                break
        routes.append(RouteEntry(verb=verb, path=norm, handler_name=fn_name,
                                 loc=Loc(rel_path, line_num, 0), module=module))

    for m in RE_DJANGO_PATH.finditer(content):
        raw_path = m.group(1)
        handler = m.group(2)
        norm = normalize_path(raw_path)
        line_num = content[:m.start()].count("\n") + 1
        routes.append(RouteEntry(verb="ANY", path=norm, handler_name=handler,
                                 loc=Loc(rel_path, line_num, 0), module=module))

    return routes


def scan_routes(root: str, py_paths: list[str]) -> RoutesIndex:
    idx = RoutesIndex()
    for path in py_paths:
        rel = os.path.relpath(path, root)
        mod = owner_of(rel)
        entries = extract_routes_from_py(path, rel, mod)
        if entries:
            file_keys: list[tuple[str, str]] = []
            for r in entries:
                key = (r.verb, r.path)
                idx.routes[key] = r
                idx.by_path.setdefault(r.path, []).append(r)
                file_keys.append(key)
            idx.by_file[rel] = file_keys
    return idx
