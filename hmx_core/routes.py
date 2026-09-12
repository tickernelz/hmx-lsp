from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace

from .locations import Loc
from .manifest import discover, owner_of

RE_NINJA_ROUTE = re.compile(
    r"""@(api|router|api_router)\.(get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]"""
)
RE_DJANGO_PATH = re.compile(
    r"""path\(\s*['"]([^'"]+)['"]\s*,\s*([a-zA-Z0-9_.]+)"""
)
RE_ROUTE_DECORATOR = re.compile(
    r"""@([A-Za-z_]\w*)\.(get|post|put|delete|patch)\(\s*['"]([^'"]+)['"]"""
)
RE_API_OPERATION = re.compile(r"@([A-Za-z_]\w*)\.api_operation\(")
RE_OP_METHODS = re.compile(r"methods\s*=\s*\[([^\]]*)\]")
RE_OP_LEADING_LIST = re.compile(r"\s*\[([^\]]*)\]")
RE_OP_PATH_KW = re.compile(r"""(?<!\w)path\s*=\s*['"]([^'"]+)['"]""")
RE_OP_STRING = re.compile(r"""['"]([^'"]+)['"]""")
RE_DJANGO_RE_PATH = re.compile(
    r"""re_path\(\s*[rRbuf]{0,2}['"]([^'"]+)['"]\s*,\s*([a-zA-Z0-9_.]+)"""
)
RE_URL_PREFIX = re.compile(r"""^[ \t]*url_prefix[ \t]*=[ \t]*['"]([^'"]*)['"]""", re.M)
RE_REGISTER_ROUTERS = re.compile(r"""register_routers\(\s*\[?\s*\(\s*['"]([^'"]*)['"]""")
RE_ADD_ROUTER = re.compile(r"""\.add_router\(\s*['"]([^'"]*)['"]""")
RE_ADD_SUBROUTER = re.compile(r"""\.add_router\(\s*['"]([^'"]*)['"]\s*,\s*([A-Za-z_]\w*)""")
RE_ROUTER_IMPORT = re.compile(
    r"""^[ \t]*from[ \t]+(\.*[\w.]*)[ \t]+import[ \t]+router[ \t]+as[ \t]+([A-Za-z_]\w*)""", re.M
)
RE_SCHEMA_CLASS = re.compile(r"""^[ \t]*class[ \t]+(\w+)[ \t]*\(([^)]*)\)[ \t]*:""", re.M)

SCHEMA_BASES = ("Schema", "ModelSchema", "BaseModel")
ROUTER_SUFFIX = "_router"
ROUTER_NAMES = ("api", "router", "api_router")
NINJA_MOUNT = "/hmx_api"


@dataclass
class RouteEntry:
    verb: str
    path: str
    handler_name: str
    loc: Loc
    module: str | None = None
    prefix: str = ""
    source: str = "ninja"


@dataclass
class RoutesIndex:
    routes: dict[tuple[str, str], RouteEntry] = field(default_factory=dict)
    by_path: dict[str, list[RouteEntry]] = field(default_factory=dict)
    by_file: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    schemas: dict[str, Loc] = field(default_factory=dict)
    prefixes: dict[str, str] = field(default_factory=dict)

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


def join_prefix(prefix: str, path: str) -> str:
    head = prefix.strip().strip("/")
    tail = normalize_path(path)
    if not head:
        return normalize_path(NINJA_MOUNT + tail)
    return normalize_path(f"{NINJA_MOUNT}/{head}{tail}")


def _is_router_name(name: str) -> bool:
    return name in ROUTER_NAMES or name.endswith(ROUTER_SUFFIX)


def _paren_segment(content: str, open_idx: int, limit: int = 4000) -> str:
    depth = 0
    stop = min(len(content), open_idx + limit)
    for i in range(open_idx, stop):
        ch = content[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return content[open_idx + 1:i]
    return content[open_idx + 1:stop]


def _handler_after(lines: list[str], line_num: int) -> str:
    for i in range(line_num, min(line_num + 12, len(lines))):
        curr = lines[i].strip()
        if curr.startswith("def ") or curr.startswith("async def "):
            return curr.split("(")[0].replace("async def ", "").replace("def ", "").strip()
    return ""


def _operation_verbs_and_path(segment: str) -> tuple[list[str], str | None]:
    methods = RE_OP_METHODS.search(segment)
    if methods is not None:
        raw_verbs = methods.group(1)
        rest = segment[:methods.start()] + segment[methods.end():]
    else:
        leading = RE_OP_LEADING_LIST.match(segment)
        if leading is not None:
            raw_verbs = leading.group(1)
            rest = segment[leading.end():]
        else:
            raw_verbs = ""
            rest = segment
    kw = RE_OP_PATH_KW.search(rest)
    if kw is not None:
        raw_path = kw.group(1)
    else:
        first = RE_OP_STRING.search(rest)
        raw_path = first.group(1) if first is not None else None
    verbs = [v.strip().strip("'\"").upper() for v in raw_verbs.split(",") if v.strip()]
    return (verbs or ["ANY"]), raw_path


def normalize_re_path(pattern: str) -> str:
    text = pattern.strip()
    if text.startswith("^"):
        text = text[1:]
    if text.endswith("$"):
        text = text[:-1]
    text = re.sub(r"\(\?P<(\w+)>[^)]*\)", r"{\1}", text)
    text = re.sub(r"\(\?[^)]*\)[?*+]?", "", text)
    text = re.sub(r"\([^)]*\)[?*+]?", "", text)
    text = text.replace("\\", "")
    return normalize_path(text)


def _source_for(module: str | None) -> str:
    return "hmx_api" if module == "hmx_api" else "ninja"


def extract_routes_from_py(path: str, rel_path: str, module: str | None) -> list[RouteEntry]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return []
    return routes_from_source(content, rel_path, module)


def routes_from_source(content: str, rel_path: str, module: str | None) -> list[RouteEntry]:
    routes: list[RouteEntry] = []
    seen: set[tuple[str, str, int]] = set()
    lines = content.splitlines()
    ninja_source = _source_for(module)

    def add(verb: str, raw_path: str, handler: str, line_num: int, source: str) -> None:
        norm = normalize_path(raw_path)
        key = (verb, norm, line_num)
        if key in seen:
            return
        seen.add(key)
        routes.append(RouteEntry(verb=verb, path=norm, handler_name=handler,
                                 loc=Loc(rel_path, line_num, 0), module=module,
                                 prefix="", source=source))

    for m in RE_ROUTE_DECORATOR.finditer(content):
        if not _is_router_name(m.group(1)):
            continue
        line_num = content[:m.start()].count("\n") + 1
        add(m.group(2).upper(), m.group(3), _handler_after(lines, line_num), line_num, ninja_source)

    for m in RE_API_OPERATION.finditer(content):
        if not _is_router_name(m.group(1)):
            continue
        segment = _paren_segment(content, m.end() - 1)
        verbs, raw_path = _operation_verbs_and_path(segment)
        if raw_path is None:
            continue
        line_num = content[:m.start()].count("\n") + 1
        handler = _handler_after(lines, line_num + segment.count("\n"))
        for verb in verbs:
            add(verb, raw_path, handler, line_num, ninja_source)

    for m in RE_DJANGO_RE_PATH.finditer(content):
        line_num = content[:m.start()].count("\n") + 1
        add("ANY", normalize_re_path(m.group(1)), m.group(2), line_num, "django")

    for m in RE_DJANGO_PATH.finditer(content):
        line_num = content[:m.start()].count("\n") + 1
        add("ANY", m.group(1), m.group(2), line_num, "django")

    return routes


def extract_schemas_from_py(path: str, rel_path: str, content: str | None = None) -> list[tuple[str, Loc]]:
    if content is None:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            return []
    found: list[tuple[str, Loc]] = []
    for m in RE_SCHEMA_CLASS.finditer(content):
        bases = m.group(2)
        if not any(re.search(rf"\b{b}\b", bases) for b in SCHEMA_BASES):
            continue
        line_num = content[:m.start()].count("\n") + 1
        found.append((m.group(1), Loc(rel_path, line_num, 0)))
    return found


def scan_url_prefixes(root: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, mod in discover(root).items():
        prefix = f"{name}/"
        apps_py = os.path.join(mod.path, "apps.py")
        if os.path.isfile(apps_py):
            try:
                with open(apps_py, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError:
                text = ""
            m = RE_URL_PREFIX.search(text)
            if m is not None:
                prefix = m.group(1)
        out[name] = prefix
    return out


def _mount_prefixes(content: str) -> list[str]:
    found: list[str] = []
    for rx in (RE_REGISTER_ROUTERS, RE_ADD_ROUTER):
        for m in rx.finditer(content):
            value = m.group(1)
            if value not in found:
                found.append(value)
    return found


def _join_mount(parent: str, child: str) -> str:
    head = parent.strip().strip("/")
    tail = child.strip().strip("/")
    if not head:
        return f"{tail}/" if tail else ""
    if not tail:
        return f"{head}/"
    return f"{head}/{tail}/"


def _module_base(rel: str) -> tuple[str, str] | None:
    parts = rel.replace("\\", "/").split("/")
    if len(parts) < 4:
        return None
    return "/".join(parts[:3]), parts[3]


def _import_target(rel: str, dotted: str) -> str | None:
    base = _module_base(rel)
    if base is None:
        return None
    holder, module = base
    text = dotted.strip()
    if text.startswith("."):
        stripped = text.lstrip(".")
        if not stripped:
            return None
        return f"{holder}/{module}/" + stripped.replace(".", "/") + ".py"
    segments = text.split(".")
    if not segments or segments[0] != module:
        return None
    return f"{holder}/" + "/".join(segments) + ".py"


def _collect_mounts(rel: str, content: str, own: dict[str, list[str]],
                    module_level: dict[str, list[str]], module: str | None) -> None:
    local: list[str] = []
    for m in RE_REGISTER_ROUTERS.finditer(content):
        if m.group(1) not in local:
            local.append(m.group(1))
    if local:
        bucket = own.setdefault(rel, [])
        for value in local:
            if value not in bucket:
                bucket.append(value)
    parent = local[0] if local else ""
    imports = {alias: dotted for dotted, alias in RE_ROUTER_IMPORT.findall(content)}
    for child_prefix, alias in RE_ADD_SUBROUTER.findall(content):
        dotted = imports.get(alias)
        if dotted is None:
            continue
        target = _import_target(rel, dotted)
        if target is None:
            continue
        value = _join_mount(parent, child_prefix)
        bucket = own.setdefault(target, [])
        if value not in bucket:
            bucket.append(value)
    if module is None:
        return
    bucket = module_level.setdefault(module, [])
    for value in _mount_prefixes(content):
        if value not in bucket:
            bucket.append(value)


def scan_routes(root: str, py_paths: list[str]) -> RoutesIndex:
    idx = RoutesIndex()
    idx.prefixes = scan_url_prefixes(root)

    file_mounts: dict[str, list[str]] = {}
    module_mounts: dict[str, list[str]] = {}
    for path in py_paths:
        rel = os.path.relpath(path, root)
        mod = owner_of(rel)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue
        for name, loc in extract_schemas_from_py(path, rel, content):
            idx.schemas.setdefault(name, loc)
        if "register_routers" in content or "add_router" in content:
            _collect_mounts(rel, content, file_mounts, module_mounts, mod)

    canonical_keys: set[tuple[str, str]] = set()
    for path in py_paths:
        rel = os.path.relpath(path, root)
        mod = owner_of(rel)
        entries = extract_routes_from_py(path, rel, mod)
        if not entries:
            continue
        candidates = _candidate_prefixes(rel, mod, idx.prefixes, file_mounts, module_mounts)
        file_keys: list[tuple[str, str]] = []
        for entry in entries:
            for key, stored, canonical in _registrations(entry, mod, idx.prefixes, candidates):
                if canonical:
                    prev = idx.routes.get(key)
                    if (key not in canonical_keys or prev is None
                            or _authority(stored) < _authority(prev)):
                        idx.routes[key] = stored
                        canonical_keys.add(key)
                elif key not in idx.routes:
                    idx.routes[key] = stored
                bucket_paths = idx.by_path.setdefault(key[1], [])
                if stored not in bucket_paths:
                    bucket_paths.append(stored)
                if key not in file_keys:
                    file_keys.append(key)
        if file_keys:
            idx.by_file[rel] = file_keys
    return idx


def _authority(entry: RouteEntry) -> int:
    parts = entry.loc.path.replace("\\", "/").split("/")
    if "tests" in parts or parts[-1].startswith("test_"):
        return 1
    return 0


def _candidate_prefixes(rel: str, module: str | None, prefixes: dict[str, str],
                        file_mounts: dict[str, list[str]],
                        module_mounts: dict[str, list[str]]) -> list[str]:
    if module is None:
        return []
    candidates = list(file_mounts.get(rel.replace("\\", "/"), []))
    for value in module_mounts.get(module, []):
        if value not in candidates:
            candidates.append(value)
    fallback = prefixes.get(module)
    if fallback is None:
        fallback = f"{module}/"
    if fallback not in candidates:
        candidates.append(fallback)
    return candidates


def _registrations(entry: RouteEntry, module: str | None, prefixes: dict[str, str],
                   candidates: list[str]) -> list[tuple[tuple[str, str], RouteEntry, bool]]:
    bare = entry.path
    if entry.source == "django":
        module_prefix = prefixes.get(module) if module else None
        head = module_prefix.strip("/") if module_prefix else ""
        if not head:
            return [((entry.verb, bare), entry, True)]
        full = normalize_path(f"/{head}{bare}")
        canonical = replace(entry, path=full, prefix=f"/{head}")
        out = [((entry.verb, full), canonical, True)]
        if full != bare:
            out.append(((entry.verb, bare), canonical, False))
        return out

    if not candidates:
        return [((entry.verb, bare), entry, True)]

    head = candidates[0].strip().strip("/")
    canonical_prefix = f"{NINJA_MOUNT}/{head}" if head else NINJA_MOUNT
    canonical = replace(entry, path=join_prefix(candidates[0], bare), prefix=canonical_prefix)
    out: list[tuple[tuple[str, str], RouteEntry, bool]] = [((entry.verb, canonical.path), canonical, True)]
    for extra in candidates[1:]:
        full = join_prefix(extra, bare)
        if full != canonical.path:
            out.append(((entry.verb, full), canonical, False))
    if bare != canonical.path:
        out.append(((entry.verb, bare), canonical, False))
    return out
