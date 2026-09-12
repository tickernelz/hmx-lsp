"""Extracts model and field declarations from HMX Python source."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from .locations import Loc

FIELD_SUFFIXES = ("Field", "ForeignKey", "OneToOneField", "ManyToManyField")
RELATIONAL = {"ForeignKey", "OneToOneField", "ManyToManyField"}
MODEL_BASES = {"models.Model", "Model"}
DJANGO_USER_BASES = {"AbstractUser", "AbstractBaseUser", "PermissionsMixin"}
META_FLAGS = ("abstract", "transient", "auto", "proxy", "auto_created")


@dataclass
class FieldDecl:
    name: str
    ctor: str
    loc: Loc
    comodel: str | None = None
    related_name: str | None = None
    delegate: bool = False


@dataclass
class PendingField:
    callee: str
    decl: "FieldDecl"


@dataclass
class ClassDecl:
    model: str
    class_name: str
    loc: Loc
    bases: list[str] = field(default_factory=list)
    direct_model: bool = False
    django_user: bool = False
    module: str | None = None
    parents: list[str] = field(default_factory=list)
    delegates: list[str] = field(default_factory=list)
    fields: list[FieldDecl] = field(default_factory=list)
    pending: list[PendingField] = field(default_factory=list)
    methods: dict[str, Loc] = field(default_factory=dict)
    abstract: bool = False
    transient: bool = False
    proxy: bool = False
    auto_created: bool = False
    auto: bool = True
    alias: str | None = None
    active_name: str | None = "active"
    auto_rule: bool | None = None


def normalize(name: str) -> str:
    return name.split(".")[-1].lower()


def _call_name(call: ast.Call) -> str:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _is_field_call(node) -> bool:
    return isinstance(node, ast.Call) and _call_name(node).endswith(FIELD_SUFFIXES)


def _keyword(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


class Constants:
    """Folds module-level constants so Meta.name = CONSTANT resolves."""

    def __init__(self, tree: ast.Module):
        self.table: dict[str, object] = {}
        for st in tree.body:
            if isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant):
                value = st.value.value
                if isinstance(value, (str, bool)):
                    for target in st.targets:
                        if isinstance(target, ast.Name):
                            self.table[target.id] = value

    def string(self, node) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            value = self.table.get(node.id)
            return value if isinstance(value, str) else None
        return None

    def strings(self, node) -> list[str]:
        one = self.string(node)
        if one:
            return [one]
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return [s for s in (self.string(e) for e in node.elts) if s]
        if isinstance(node, ast.Dict):
            return [s for s in (self.string(k) for k in node.keys) if s]
        return []

    def boolean(self, node) -> bool | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name):
            value = self.table.get(node.id)
            return value if isinstance(value, bool) else None
        return None

    def truthy(self, node) -> bool | None:
        flag = self.boolean(node)
        if flag is not None:
            return flag
        return True if isinstance(node, ast.Dict) else None


def _unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _read_meta(node: ast.ClassDef, const: Constants, decl: ClassDecl) -> tuple[str | None, bool]:
    meta_name = None
    declared = False
    for sub in node.body:
        if not (isinstance(sub, ast.ClassDef) and sub.name == "Meta"):
            continue
        for st in sub.body:
            if not isinstance(st, ast.Assign):
                continue
            for target in st.targets:
                if not isinstance(target, ast.Name):
                    continue
                key, value = target.id, st.value
                if key == "name":
                    declared = True
                    meta_name = const.string(value)
                elif key == "inherit":
                    decl.parents += const.strings(value)
                elif key == "inherits":
                    got = const.strings(value)
                    decl.parents += got
                    decl.delegates += got
                elif key in META_FLAGS:
                    flag = const.boolean(value)
                    if flag is not None:
                        setattr(decl, key, flag)
                elif key == "auto_rule":
                    decl.auto_rule = const.truthy(value)
                elif key == "alias":
                    decl.alias = const.string(value)
                elif key == "active_name":
                    decl.active_name = const.string(value)
    return meta_name, declared


def _read_field(st: ast.Assign, const: Constants, rel: str) -> list[FieldDecl]:
    call = st.value
    ctor = _call_name(call)
    comodel = None
    if ctor in RELATIONAL:
        target = call.args[0] if call.args else _keyword(call, "to")
        if target is not None:
            literal = const.string(target)
            comodel = normalize(literal) if literal else (
                target.id.lower() if isinstance(target, ast.Name) else None)
    rn_node = _keyword(call, "related_name")
    related_name = const.string(rn_node) if rn_node is not None else None
    dl_node = _keyword(call, "delegate")
    delegate = bool(const.boolean(dl_node)) if dl_node is not None else False
    return [FieldDecl(t.id, ctor, Loc(rel, st.lineno), comodel, related_name, delegate)
            for t in st.targets if isinstance(t, ast.Name)]


def field_factories(tree: ast.Module) -> set[str]:
    """Functions whose body returns a field constructor; their calls declare fields."""
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Return) and _is_field_call(sub.value):
                out.add(node.name)
                break
    return out


def extract(source: bytes, rel_path: str, module: str | None) -> tuple[list[ClassDecl], set[str]]:
    """Model classes in this file, plus any field-factory functions it defines."""
    tree = ast.parse(source)
    const = Constants(tree)
    factories = field_factories(tree)
    out: list[ClassDecl] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not node.bases:
            continue
        bases = [_unparse(b) for b in node.bases]
        short = [b.split("(")[0].strip().split(".")[-1] for b in bases if b]
        decl = ClassDecl(model="", class_name=node.name, loc=Loc(rel_path, node.lineno),
                         bases=short, module=module,
                         direct_model=any(b in MODEL_BASES or b.endswith(".Model") for b in bases),
                         django_user=any(b in DJANGO_USER_BASES for b in short))
        meta_name, declared = _read_meta(node, const, decl)
        if meta_name:
            decl.model = normalize(meta_name)
        elif not declared and len(decl.parents) == 1:
            decl.model = normalize(decl.parents[0])
        else:
            decl.model = node.name.lower()
        decl.parents = [p for p in (normalize(x) for x in decl.parents) if p != decl.model]
        decl.delegates = [p for p in (normalize(x) for x in decl.delegates) if p != decl.model]
        for st in node.body:
            if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decl.methods[st.name] = Loc(rel_path, st.lineno, getattr(st, "col_offset", 0))
                continue
            if not isinstance(st, ast.Assign) or not isinstance(st.value, ast.Call):
                continue
            if _is_field_call(st.value):
                for fd in _read_field(st, const, rel_path):
                    decl.fields.append(fd)
                    if fd.delegate and fd.comodel:
                        decl.delegates.append(fd.comodel)
                continue
            callee = _call_name(st.value)
            if callee:
                for target in st.targets:
                    if isinstance(target, ast.Name):
                        decl.pending.append(PendingField(
                            callee, FieldDecl(target.id, callee, Loc(rel_path, st.lineno))))
        if decl.direct_model or decl.django_user or declared or decl.parents or decl.fields or decl.methods:
            out.append(decl)
    return out, factories
