"""Extracts model and field declarations from HMX Python source."""

from __future__ import annotations

import ast
import re
import io
import tokenize
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
    compute: str | None = None
    inverse: str | None = None
    search_method: str | None = None
    domain: str | None = None
    choices: list[str] = field(default_factory=list)
    string: str | None = None
    company_dependent: bool = False


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
    ordering: list[str] = field(default_factory=list)
    rec_name: str | None = None
    company_field: str | None = None
    branch_field: str | None = None
    unique_together: list[list[str]] = field(default_factory=list)


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
    """Folds module-level and class-level constants so Meta.name = CONSTANT resolves."""

    def __init__(self, tree: ast.Module):
        self.table: dict[str, object] = {}
        self.sequences: dict[str, ast.List | ast.Tuple] = {}
        self.absorb(tree.body)

    def absorb(self, body) -> None:
        for st in body:
            if not isinstance(st, ast.Assign):
                continue
            if isinstance(st.value, ast.Constant):
                value = st.value.value
                if isinstance(value, (str, bool)):
                    for target in st.targets:
                        if isinstance(target, ast.Name):
                            self.table[target.id] = value
            elif isinstance(st.value, (ast.List, ast.Tuple)):
                for target in st.targets:
                    if isinstance(target, ast.Name):
                        self.sequences[target.id] = st.value

    def scoped(self, node: ast.ClassDef) -> "Constants":
        child = Constants(ast.Module(body=[], type_ignores=[]))
        child.table = dict(self.table)
        child.sequences = dict(self.sequences)
        child.absorb(node.body)
        return child

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

    def sequence(self, node) -> ast.List | ast.Tuple | None:
        if isinstance(node, (ast.List, ast.Tuple)):
            return node
        if isinstance(node, ast.Name):
            return self.sequences.get(node.id)
        return None

    def string_list(self, node) -> list[str]:
        seq = self.sequence(node)
        if seq is None:
            return self.strings(node)
        return [s for s in (self.string(e) for e in seq.elts) if s]

    def choices(self, node) -> list[str]:
        seq = self.sequence(node)
        if seq is None:
            return []
        out: list[str] = []
        for elt in seq.elts:
            if not isinstance(elt, (ast.Tuple, ast.List)) or len(elt.elts) != 2:
                continue
            text = _literal_text(elt.elts[0])
            if text is not None:
                out.append(text)
        return out

    def groups(self, node) -> list[list[str]]:
        seq = self.sequence(node)
        if seq is None:
            return []
        nested = [e for e in seq.elts if isinstance(e, (ast.Tuple, ast.List))]
        if nested:
            out = []
            for e in nested:
                names = [s for s in (self.string(x) for x in e.elts) if s]
                if names:
                    out.append(names)
            return out
        flat = [s for s in (self.string(e) for e in seq.elts) if s]
        return [flat] if flat else []


def _literal_text(node) -> str | None:
    if not isinstance(node, ast.Constant):
        return None
    value = node.value
    if isinstance(value, str):
        return value
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _text(node, const: Constants) -> str | None:
    found = const.string(node)
    if found:
        return found
    if isinstance(node, ast.Call) and len(node.args) == 1:
        return const.string(node.args[0])
    return None


def _method_ref(node, const: Constants) -> str | None:
    found = const.string(node)
    if found:
        return found
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _unparse(node) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _scoped_field(value, const: Constants, default: str) -> str | None:
    found = const.string(value)
    if found:
        return found
    if isinstance(value, ast.Dict):
        for key, item in zip(value.keys, value.values):
            if isinstance(key, ast.Constant) and key.value in ("name", "field_name"):
                named = const.string(item)
                if named:
                    return named
        return default
    return None


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
                elif key == "ordering":
                    decl.ordering = const.string_list(value)
                elif key in ("rec_name", "_rec_name"):
                    decl.rec_name = const.string(value)
                elif key == "company_field":
                    decl.company_field = _scoped_field(value, const, "company")
                elif key == "branch_field":
                    decl.branch_field = _scoped_field(value, const, "branch")
                elif key == "unique_together":
                    decl.unique_together = const.groups(value)
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
    extra = _read_field_extras(call, const)
    return [FieldDecl(t.id, ctor, Loc(rel, st.lineno), comodel, related_name, delegate, **extra)
            for t in st.targets if isinstance(t, ast.Name)]


def _read_field_extras(call: ast.Call, const: Constants) -> dict:
    compute = inverse = search_method = domain = string = None
    choices: list[str] = []
    company_dependent = False
    for kw in call.keywords:
        if kw.arg == "compute":
            compute = _method_ref(kw.value, const)
        elif kw.arg == "inverse":
            inverse = _method_ref(kw.value, const)
        elif kw.arg == "search":
            search_method = _method_ref(kw.value, const)
        elif kw.arg == "domain":
            domain = const.string(kw.value) or _unparse(kw.value) or None
        elif kw.arg == "choices":
            choices = const.choices(kw.value)
        elif kw.arg == "verbose_name":
            string = _text(kw.value, const)
        elif kw.arg == "company_dependent":
            company_dependent = bool(const.truthy(kw.value))
    return {"compute": compute, "inverse": inverse, "search_method": search_method,
            "domain": domain, "choices": choices, "string": string,
            "company_dependent": company_dependent}


def selections_of(decl: ClassDecl) -> dict[str, list[str]]:
    return {fd.name: list(fd.choices) for fd in decl.fields if fd.choices}


def computes_of(decl: ClassDecl) -> dict[str, str]:
    return {fd.name: fd.compute for fd in decl.fields if fd.compute}


def kinds_of(decl: ClassDecl) -> dict[str, str]:
    return {fd.name: fd.ctor for fd in decl.fields if fd.ctor}


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


def _protected_source_lines(source: str) -> set[int]:
    protected: set[int] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type not in (tokenize.STRING, tokenize.COMMENT):
                continue
            protected.update(range(token.start[0], token.end[0] + 1))
    except (tokenize.TokenError, IndentationError):
        return protected
    return protected


def _parenthesize_except_groups(source: str) -> tuple[str, dict[int, tuple[int, int]]]:
    protected = _protected_source_lines(source)
    lines = source.splitlines(keepends=True)
    out: list[str] = []
    shifts: dict[int, tuple[int, int]] = {}
    for number, line in enumerate(lines, start=1):
        match = re.match(r"^(\s*except\s+)([^:\n]+)(:.*)$", line)
        if number in protected or not match:
            out.append(line)
            continue
        body = match.group(2)
        if "," not in body or body.lstrip().startswith("("):
            out.append(line)
            continue
        prefix = match.group(1)
        out.append(f"{prefix}({body}){match.group(3)}")
        body_start = len(prefix.encode("utf-8"))
        close_start = body_start + 1 + len(body.encode("utf-8"))
        shifts[number] = (body_start, close_start)
    return "".join(out), shifts


def _restore_columns(tree: ast.Module, shifts: dict[int, tuple[int, int]]) -> None:
    def restore(line: int, col: int) -> int:
        if line not in shifts:
            return col
        body_start, close_start = shifts[line]
        if col >= close_start:
            return max(0, col - 2)
        if col > body_start:
            return max(0, col - 1)
        return col

    for node in ast.walk(tree):
        for attr in ("col_offset", "end_col_offset"):
            line = getattr(node, "lineno" if attr == "col_offset" else "end_lineno", None)
            col = getattr(node, attr, None)
            if line is not None and col is not None:
                setattr(node, attr, restore(line, col))


def parse_source(source: bytes | str) -> ast.Module:
    if isinstance(source, bytes):
        try:
            return ast.parse(source)
        except SyntaxError:
            text = source.decode("utf-8")
    else:
        text = source
    try:
        return ast.parse(text)
    except SyntaxError:
        transformed, shifts = _parenthesize_except_groups(text)
        if transformed == text:
            raise
        tree = ast.parse(transformed)
        _restore_columns(tree, shifts)
        return tree


def extract(source: bytes, rel_path: str, module: str | None) -> tuple[list[ClassDecl], set[str]]:
    """Model classes in this file, plus any field-factory functions it defines."""
    tree = parse_source(source)
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
        scope = const.scoped(node)
        meta_name, declared = _read_meta(node, scope, decl)
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
                for fd in _read_field(st, scope, rel_path):
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
