from __future__ import annotations

import ast
import pathlib
import re

from .pysource import Constants, parse_source


_CALL = re.compile(r"\.\s*([A-Za-z_]\w*)\s*\(")


def parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    values = [*function.args.posonlyargs, *function.args.args]
    if values and values[0].arg in ("self", "cls"):
        values = values[1:]
    return [*values, *function.args.kwonlyargs]


def source_tree(resolver, relative: str) -> ast.Module:
    path = pathlib.Path(resolver.index.root) / relative
    stat = path.stat()
    stamp = stat.st_mtime_ns, stat.st_size
    cached = resolver._source_trees.get(str(path))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    tree = parse_source(path.read_bytes())
    resolver._source_trees[str(path)] = stamp, tree
    return tree


def caller_files(resolver, method: str) -> list[str]:
    if resolver._caller_files is None:
        by_name: dict[str, list[str]] = {}
        for relative in resolver.index.file_models:
            try:
                text = (pathlib.Path(resolver.index.root) / relative).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for name in set(_CALL.findall(text)):
                by_name.setdefault(name, []).append(relative)
        resolver._caller_files = by_name
    return resolver._caller_files.get(method, [])


def method_definition(model: str, method: str, resolver):
    loc = resolver.methods(model).get(method)
    root = getattr(resolver.index, "root", "")
    if loc is None or not root or loc.path.startswith("<"):
        return None
    try:
        tree = source_tree(resolver, loc.path)
    except (OSError, SyntaxError, ValueError):
        return None
    return next((node for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and node.name == method and node.lineno == loc.line), None)


def argument_models(call, function, bindings, model, resolver) -> tuple[str | None, ...]:
    from .locals import model_of_expr

    names = parameters(function)
    values = [None] * len(names)
    positional = len(function.args.posonlyargs) + len(function.args.args)
    if function.args.posonlyargs or function.args.args:
        first = [*function.args.posonlyargs, *function.args.args][0].arg
        positional -= int(first in ("self", "cls"))
    for i, node in enumerate(call.args[:positional]):
        if i < len(values) and not isinstance(node, ast.Starred):
            values[i] = model_of_expr(node, bindings, model, resolver)
    for keyword in call.keywords:
        for i, parameter in enumerate(names):
            if keyword.arg == parameter.arg:
                values[i] = model_of_expr(keyword.value, bindings, model, resolver)
    return tuple(values)


def infer_parameters(function, model: str, resolver) -> tuple[str | None, ...]:
    from .locals import class_model, local_models, model_of_expr

    key = model, function.name
    if key in resolver._method_call_args:
        return resolver._method_call_args[key]
    if key in resolver._parameter_inflight or len(resolver._parameter_inflight) >= 16:
        return ()
    resolver._parameter_inflight.add(key)
    observations: list[tuple[str | None, ...]] = []
    try:
        for relative in caller_files(resolver, function.name):
            try:
                tree = source_tree(resolver, relative)
            except (OSError, SyntaxError, ValueError):
                continue
            constants = Constants(tree)
            for cls in tree.body:
                if not isinstance(cls, ast.ClassDef):
                    continue
                owner = class_model(cls, constants)
                if not owner or not resolver.known(owner):
                    continue
                for caller in cls.body:
                    if not isinstance(caller, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    calls = [node for node in ast.walk(caller)
                             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                             and node.func.attr == function.name]
                    if not calls:
                        continue
                    caller_params = parameters(caller)
                    parameter_models = (infer_parameters(caller, owner, resolver)
                                        if caller_params else ())
                    bindings = local_models(caller, owner, resolver,
                                            parameter_models=parameter_models)
                    for call in calls:
                        receiver = model_of_expr(call.func.value, bindings, owner, resolver)
                        if receiver == model:
                            observations.append(argument_models(call, function, bindings, owner, resolver))
        result = []
        for i in range(len(parameters(function))):
            choices = {values[i] for values in observations}
            result.append(next(iter(choices)) if len(choices) == 1 and None not in choices else None)
        inferred = tuple(result)
        resolver._method_call_args[key] = inferred
        return inferred
    finally:
        resolver._parameter_inflight.discard(key)
