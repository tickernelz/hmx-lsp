from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass
class PyCursorContext:
    kind: str
    value: str
    active_model: str | None = None
    hop_index: int = 0
    secondary_value: str | None = None
    range: tuple[tuple[int, int], tuple[int, int]] | None = None


class _NodeFinder(ast.NodeVisitor):
    def __init__(self, line: int, col: int):
        self.line = line
        self.col = col
        self.path: list[ast.AST] = []
        self.best: list[ast.AST] = []

    def generic_visit(self, node: ast.AST):
        lineno = getattr(node, "lineno", None)
        end_lineno = getattr(node, "end_lineno", None)
        col_offset = getattr(node, "col_offset", None)
        end_col_offset = getattr(node, "end_col_offset", None)

        if lineno is not None and end_lineno is not None:
            if lineno <= self.line <= end_lineno:
                if (lineno < self.line or col_offset <= self.col) and (self.line < end_lineno or self.col <= end_col_offset):
                    self.path.append(node)
                    self.best = list(self.path)
                    super().generic_visit(node)
                    self.path.pop()
                    return
        super().generic_visit(node)


def _find_enclosing_model(stack: list[ast.AST]) -> str | None:
    for node in reversed(stack):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.ClassDef) and item.name == "Meta":
                    for stmt in item.body:
                        if isinstance(stmt, ast.Assign):
                            for target in stmt.targets:
                                if isinstance(target, ast.Name) and target.id == "name":
                                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                                        return stmt.value.value.lower()
    return None


def resolve_py_cursor(content: str, line: int, col: int) -> PyCursorContext | None:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None

    finder = _NodeFinder(line, col)
    finder.visit(tree)
    if not finder.best:
        return None

    stack = finder.best
    node = stack[-1]
    active_model = _find_enclosing_model(stack)

    for p_node in reversed(stack):
        if isinstance(p_node, ast.Attribute):
            val = p_node.value
            if isinstance(val, ast.Name) and val.id == "api":
                rng = ((p_node.lineno, val.col_offset), (p_node.end_lineno, p_node.end_col_offset))
                return PyCursorContext(kind="decorator", value=f"api.{p_node.attr}",
                                       active_model=active_model, range=rng)

    if isinstance(node, ast.Name):
        rng = ((node.lineno, node.col_offset), (node.end_lineno, node.end_col_offset))
        if len(stack) >= 2 and isinstance(stack[-2], ast.Assign):
            parent = stack[-2]
            if node in parent.targets:
                return PyCursorContext(kind="field", value=node.id, active_model=active_model, range=rng)
        return PyCursorContext(kind="name", value=node.id, active_model=active_model, range=rng)

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        val = node.value
        rng = ((node.lineno, node.col_offset), (node.end_lineno, node.end_col_offset))
        if len(stack) >= 2:
            parent = stack[-2]

            if isinstance(parent, ast.Call):
                func = parent.func
                func_name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                func_mod = func.value.id if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)) else ""

                if func_mod == "api":
                    if func_name in ("depends", "onchange", "constrains"):
                        parts = val.split(".")
                        hop = 0
                        rel_col = col - node.col_offset - 1
                        curr_len = 0
                        for idx, p in enumerate(parts):
                            curr_len += len(p)
                            if rel_col <= curr_len:
                                hop = idx
                                break
                            curr_len += 1
                        return PyCursorContext(kind="dotted_field", value=val,
                                               active_model=active_model, hop_index=hop,
                                               secondary_value=f"api.{func_name}", range=rng)

                    if func_name == "transition":
                        arg_idx = parent.args.index(node) if node in parent.args else 0
                        if arg_idx == 0:
                            return PyCursorContext(kind="field", value=val,
                                                   active_model=active_model, range=rng)
                        return PyCursorContext(kind="state_value", value=val,
                                               active_model=active_model, range=rng)

                    if func_name == "returns":
                        return PyCursorContext(kind="model", value=val.lower(),
                                               active_model=active_model, range=rng)

                    if func_name == "depends_context":
                        return PyCursorContext(kind="context_key", value=val,
                                               active_model=active_model, range=rng)

                if func_name in ("ForeignKey", "OneToOneField", "ManyToManyField"):
                    target_model = val.split(".")[-1].lower()
                    return PyCursorContext(kind="model", value=target_model,
                                           active_model=active_model, range=rng)
                if func_name == "ref":
                    return PyCursorContext(kind="xmlid", value=val,
                                           active_model=active_model, range=rng)

            if isinstance(parent, ast.Subscript):
                slice_node = parent.slice
                if slice_node is node:
                    base = parent.value
                    if isinstance(base, ast.Attribute) and base.attr == "env":
                        return PyCursorContext(kind="model", value=val.lower(),
                                               active_model=active_model, range=rng)
                    if isinstance(base, ast.Name) and base.id == "env":
                        return PyCursorContext(kind="model", value=val.lower(),
                                               active_model=active_model, range=rng)

            if isinstance(parent, ast.keyword) and parent.arg in ("related", "depends"):
                parts = val.split(".")
                hop = 0
                rel_col = col - node.col_offset - 1
                curr_len = 0
                for idx, p in enumerate(parts):
                    curr_len += len(p)
                    if rel_col <= curr_len:
                        hop = idx
                        break
                    curr_len += 1
                return PyCursorContext(kind="dotted_field", value=val,
                                       active_model=active_model, hop_index=hop, range=rng)

        return PyCursorContext(kind="string", value=val, active_model=active_model, range=rng)

    return None
