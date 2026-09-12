from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field

APP_ROOTS = ("basic", "core", "modifier")


@dataclass
class Module:
    name: str
    path: str
    depends: list[str] = field(default_factory=list)
    data: list[str] = field(default_factory=list)
    demo: list[str] = field(default_factory=list)
    active_rule: bool = False
    installable: bool = True


def _payload(tree: ast.Module) -> dict | None:
    for st in tree.body:
        node = st.value if isinstance(st, (ast.Expr, ast.Assign)) else None
        if node is None:
            continue
        try:
            value = ast.literal_eval(node)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, dict):
            return value
    return None


def read_manifest(path: str, name: str) -> Module | None:
    try:
        tree = ast.parse(open(path, "rb").read())
    except (SyntaxError, OSError):
        return None
    payload = _payload(tree)
    if payload is None:
        return None
    strings = lambda key: [v for v in (payload.get(key) or []) if isinstance(v, str)]
    return Module(name=name, path=os.path.dirname(path), depends=strings("depends"),
                  data=strings("data"), demo=strings("demo"),
                  active_rule=bool(payload.get("active_rule", False)),
                  installable=bool(payload.get("installable", True)))


def discover(root: str) -> dict[str, Module]:
    out: dict[str, Module] = {}
    base = os.path.join(root, "hmx", "module")
    for app_root in APP_ROOTS:
        holder = os.path.join(base, app_root)
        if not os.path.isdir(holder):
            continue
        for name in sorted(os.listdir(holder)):
            manifest = os.path.join(holder, name, "__hmx__.py")
            if os.path.isfile(manifest):
                mod = read_manifest(manifest, name)
                if mod is not None:
                    out[name] = mod
    return out


def owner_of(rel_path: str) -> str | None:
    parts = rel_path.split(os.sep)
    if len(parts) >= 4 and parts[0] == "hmx" and parts[1] == "module" and parts[2] in APP_ROOTS:
        return parts[3]
    return None
