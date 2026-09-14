from __future__ import annotations

import ast
import pathlib
from typing import Protocol

from hmx_core.pysource import Constants, parse_source

SELF_NAMES = frozenset({"self"})
CHAINING_METHODS = frozenset({
    "filtered", "filtered_domain", "sorted", "browse", "exists", "search", "sudo",
    "with_context", "with_company", "with_user", "with_env", "create", "copy",
    "ensure_one", "union", "concat", "first", "last", "refresh", "new",
})
LAMBDA_METHODS = frozenset({"filtered", "sorted", "mapped", "map", "any", "all"})
RECORDSET_ATTRS = frozenset({
    "id", "ids", "env", "pool", "_name", "_table", "_fields", "_context", "_origin",
    "display_name", "create_date", "write_date", "create_uid", "write_uid",
    "pk", "objects", "DoesNotExist", "MultipleObjectsReturned",
    "all", "filter", "exclude", "get", "get_or_create", "update_or_create",
    "values", "values_list", "count", "order_by", "distinct", "annotate",
    "aggregate", "select_related", "prefetch_related", "only", "defer",
    "delete", "update", "save", "refresh_from_db", "bulk_create", "bulk_update",
    "iterator", "in_bulk", "earliest", "latest", "none", "using", "raw",
})


def is_framework_attr(name: str) -> bool:
    if name in RECORDSET_ATTRS or name.startswith("_") or name.isupper():
        return True
    return name.startswith("get_") and name.endswith(("_display", "_url"))


class ModelResolver(Protocol):
    def known(self, model: str) -> bool: ...

    def comodel(self, model: str, name: str) -> str | None: ...


def _env_model(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript):
        return None
    base = node.value
    if not (isinstance(base, ast.Attribute) and base.attr == "env"):
        return None
    key = node.slice
    if isinstance(key, ast.Constant) and isinstance(key.value, str):
        return key.value.lower()
    return None


def _literal_strings(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out: list[str] = []
        for item in node.elts:
            out.extend(_literal_strings(item))
        return out
    return []


def class_model(node: ast.ClassDef, constants: Constants | None = None) -> str | None:
    explicit: str | None = None
    parents: list[str] = []
    scope = constants.scoped(node) if constants else None
    for item in node.body:
        if not (isinstance(item, ast.ClassDef) and item.name == "Meta"):
            continue
        for stmt in item.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "name":
                    value = scope.string(stmt.value) if scope else None
                    values = [value] if value else _literal_strings(stmt.value)
                    if values:
                        explicit = values[0].lower()
                elif target.id in ("inherit", "inherits"):
                    values = scope.strings(stmt.value) if scope else _literal_strings(stmt.value)
                    parents.extend(value.lower().split(".")[-1] for value in values)
    if explicit:
        return explicit
    if len(parents) == 1:
        return parents[0]
    return node.name.lower()


def _returns_in_scope(function: ast.AST) -> list[ast.Return]:
    out: list[ast.Return] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Return):
                out.append(child)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            else:
                visit(child)

    visit(function)
    return out


def _empty_return(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in (None, False)


def model_of_return(node: ast.AST, bindings: dict[str, str], model: str,
                    resolver: ModelResolver) -> str | None:
    if isinstance(node, ast.IfExp):
        body = None if _empty_return(node.body) else model_of_expr(node.body, bindings, model, resolver)
        orelse = None if _empty_return(node.orelse) else model_of_expr(node.orelse, bindings, model, resolver)
        if body and orelse and body != orelse:
            return None
        return body or orelse
    return None if _empty_return(node) else model_of_expr(node, bindings, model, resolver)


def method_result_model(model: str, method: str, resolver: ModelResolver,
                       seen: frozenset[tuple[str, str]] = frozenset()) -> str | None:
    key = (model, method)
    if key in seen:
        return None
    cache = getattr(resolver, "_method_result_models", None)
    if cache is None:
        cache = {}
        resolver._method_result_models = cache
    if key in cache:
        return cache[key]
    inflight = getattr(resolver, "_method_result_inflight", None)
    if inflight is None:
        inflight = set()
        resolver._method_result_inflight = inflight
    if key in inflight:
        return None
    inflight.add(key)
    entry = getattr(resolver, "index", None)
    root = getattr(entry, "root", "") if entry is not None else ""
    methods = resolver_methods(resolver, model)
    loc = methods.get(method)
    try:
        if loc is None or loc.path.startswith("<") or not root:
            cache[key] = None
            return None
        path = pathlib.Path(root) / loc.path
        try:
            tree = parse_source(path.read_bytes())
        except (OSError, SyntaxError, ValueError):
            cache[key] = None
            return None
        for node in ast.walk(tree):
            if (not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    or node.name != method or node.lineno != loc.line):
                continue
            bindings = {"self": model}
            found_models: set[str] = set()
            unresolved = False
            saw_return = False
            for returned in _returns_in_scope(node):
                if not isinstance(returned, ast.Return) or returned.value is None:
                    continue
                saw_return = True
                found = model_of_return(returned.value, bindings, model, resolver)
                if found and resolver.known(found):
                    found_models.add(found)
                elif not _empty_return(returned.value):
                    unresolved = True
            if saw_return and not unresolved and len(found_models) == 1:
                value = next(iter(found_models))
                cache[key] = value
                return value
            cache[key] = None
            return None
        cache[key] = None
        return None
    finally:
        inflight.discard(key)


def resolver_methods(resolver: ModelResolver, model: str) -> dict[str, object]:
    getter = getattr(resolver, "methods", None)
    return getter(model) if getter is not None else {}


def model_of_expr(node: ast.AST, bindings: dict[str, str], model: str | None,
                  resolver: ModelResolver | None) -> str | None:
    if isinstance(node, ast.Name):
        if node.id in SELF_NAMES:
            return model
        return bindings.get(node.id)

    direct = _env_model(node)
    if direct:
        return direct

    if isinstance(node, ast.Attribute):
        base = model_of_expr(node.value, bindings, model, resolver)
        if base and resolver is not None:
            return resolver.comodel(base, node.attr)
        return None

    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in CHAINING_METHODS:
                return model_of_expr(func.value, bindings, model, resolver)
            base = model_of_expr(func.value, bindings, model, resolver)
            if base and resolver is not None:
                found = method_result_model(base, func.attr, resolver)
                if found:
                    return found
            if func.attr == "mapped" and node.args:
                arg = node.args[0]
                base = model_of_expr(func.value, bindings, model, resolver)
                if (base and resolver is not None and isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)):
                    current: str | None = base
                    for hop in arg.value.split("."):
                        if current is None:
                            return None
                        current = resolver.comodel(current, hop)
                    return current
        return None

    if isinstance(node, (ast.Subscript, ast.BinOp)):
        target = node.value if isinstance(node, ast.Subscript) else node.left
        return model_of_expr(target, bindings, model, resolver)

    if isinstance(node, ast.IfExp):
        body = None if _empty_return(node.body) else model_of_expr(node.body, bindings, model, resolver)
        orelse = None if _empty_return(node.orelse) else model_of_expr(node.orelse, bindings, model, resolver)
        return body if body and body == orelse else None

    if isinstance(node, ast.BoolOp):
        models = [model_of_expr(value, bindings, model, resolver) for value in node.values]
        known = {value for value in models if value}
        return next(iter(known)) if len(known) == 1 else None

    return None


def _bind_lambda(call: ast.Call, bindings: dict[str, str], model: str | None,
                 resolver: ModelResolver | None) -> None:
    func = call.func
    if not (isinstance(func, ast.Attribute) and func.attr in LAMBDA_METHODS):
        return
    base = model_of_expr(func.value, bindings, model, resolver)
    if not base:
        return
    for arg in call.args:
        if isinstance(arg, ast.Lambda) and arg.args.args:
            bindings[arg.args.args[0].arg] = base


def _bind_targets(target: ast.AST, source: ast.AST, bindings: dict[str, str],
                  model: str | None, resolver: ModelResolver | None) -> None:
    found = model_of_expr(source, bindings, model, resolver)
    if not found:
        return
    if isinstance(target, ast.Name):
        bindings[target.id] = found
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            if isinstance(element, ast.Name):
                bindings[element.id] = found


def local_models(func: ast.AST, model: str | None,
                 resolver: ModelResolver | None) -> dict[str, str]:
    bindings: dict[str, str] = {}
    if model:
        bindings["self"] = model

    for _ in range(3):
        before = dict(bindings)
        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                _bind_lambda(node, bindings, model, resolver)
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                _bind_targets(node.target, node.iter, bindings, model, resolver)
            elif isinstance(node, ast.comprehension):
                _bind_targets(node.target, node.iter, bindings, model, resolver)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    _bind_targets(target, node.value, bindings, model, resolver)
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)):
                if node.value is not None:
                    _bind_targets(node.target, node.value, bindings, model, resolver)
            elif isinstance(node, ast.withitem):
                if node.optional_vars is not None:
                    _bind_targets(node.optional_vars, node.context_expr, bindings,
                                  model, resolver)
        if bindings == before:
            break
    return bindings


def enclosing_function(stack: list[ast.AST]) -> ast.AST | None:
    for node in reversed(stack):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None
