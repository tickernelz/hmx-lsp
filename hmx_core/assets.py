from __future__ import annotations

import ast
import glob
import os
from dataclasses import dataclass, field

from .locations import Loc

MANIFEST = "__hmx__.py"
SKIP_DIRS = (".git", "node_modules", "__pycache__")


@dataclass
class AssetEntry:
    bundle: str
    pattern: str
    module: str
    loc: Loc
    matches: int = 0


@dataclass
class AssetIndex:
    bundles: dict[str, list[AssetEntry]] = field(default_factory=dict)
    by_module: dict[str, list[AssetEntry]] = field(default_factory=dict)
    by_file: dict[str, list[AssetEntry]] = field(default_factory=dict)

    def known_bundle(self, name: str) -> bool:
        return bool(name) and name in self.bundles

    def forget_file(self, rel_path: str) -> None:
        for stale in self.by_file.pop(rel_path, []):
            bucket = self.bundles.get(stale.bundle)
            if bucket is not None:
                self.bundles[stale.bundle] = [e for e in bucket if e is not stale]
            owned = self.by_module.get(stale.module)
            if owned is not None:
                self.by_module[stale.module] = [e for e in owned if e is not stale]

    def update_file(self, rel_path: str, abs_path: str) -> None:
        self.forget_file(rel_path)
        module_dir = os.path.dirname(abs_path)
        names, entries = _collect(abs_path, rel_path, os.path.basename(module_dir))
        for name in names:
            self.bundles.setdefault(name, [])
        for entry in entries:
            entry.matches = len(glob.glob(os.path.join(module_dir, entry.pattern), recursive=True))
            self.bundles.setdefault(entry.bundle, []).append(entry)
            self.by_module.setdefault(entry.module, []).append(entry)
        if entries:
            self.by_file[rel_path] = entries

    def dead(self) -> list[AssetEntry]:
        return [e for entries in self.bundles.values() for e in entries if e.matches == 0]


def _assets_dicts(tree: ast.Module) -> list[ast.Dict]:
    out: list[ast.Dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "assets" and isinstance(value, ast.Dict):
                out.append(value)
    return out


def _from_tree(tree: ast.Module, rel_path: str,
               module: str) -> tuple[list[str], list[AssetEntry]]:
    names: list[str] = []
    entries: list[AssetEntry] = []
    for holder in _assets_dicts(tree):
        for key, value in zip(holder.keys, holder.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if not isinstance(value, ast.List):
                continue
            names.append(key.value)
            for item in value.elts:
                if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                    continue
                loc = Loc(rel_path, item.lineno, item.col_offset)
                entries.append(AssetEntry(key.value, item.value, module, loc))
    return names, entries


def _collect(path: str, rel_path: str, module: str) -> tuple[list[str], list[AssetEntry]]:
    try:
        tree = ast.parse(open(path, "rb").read())
    except (SyntaxError, OSError, ValueError):
        return [], []
    return _from_tree(tree, rel_path, module)


def extract_assets_from_manifest(path: str, rel_path: str, module: str) -> list[AssetEntry]:
    return _collect(path, rel_path, module)[1]


def assets_from_source(content: str, rel_path: str, module_dir: str) -> list[AssetEntry]:
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return []
    entries = _from_tree(tree, rel_path, os.path.basename(module_dir))[1]
    for entry in entries:
        entry.matches = len(glob.glob(os.path.join(module_dir, entry.pattern), recursive=True))
    return entries


def scan_assets(root: str) -> AssetIndex:
    idx = AssetIndex()
    module_dir = os.path.join(root, "hmx", "module")
    if not os.path.isdir(module_dir):
        return idx

    for dirpath, _, filenames in os.walk(module_dir):
        if any(s in dirpath for s in SKIP_DIRS):
            continue
        if MANIFEST not in filenames:
            continue
        path = os.path.join(dirpath, MANIFEST)
        rel = os.path.relpath(path, root)
        module = os.path.basename(dirpath)
        names, entries = _collect(path, rel, module)
        for name in names:
            idx.bundles.setdefault(name, [])
        for entry in entries:
            entry.matches = len(glob.glob(os.path.join(dirpath, entry.pattern), recursive=True))
            idx.bundles[entry.bundle].append(entry)
            idx.by_module.setdefault(module, []).append(entry)
        if entries:
            idx.by_file[rel] = entries

    return idx
