from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from .injection import DJANGO_USER_FIELDS, EXTERNAL_BASE_FIELDS, injected
from .locations import Loc
from .manifest import Module, discover, owner_of
from .pysource import ClassDecl, extract
from .routes import RoutesIndex, scan_routes
from .security import SecurityIndex, scan_security
from .webx import WebxIndex, extract_js_file, extract_vue_file, scan_webx
from .xmlids import XmlIdIndex, extract_xmlids_from_tree, scan_xmlids
from lxml import etree

SKIP_DIRS = {"node_modules", ".git", "__pycache__", "test-results", "static",
             ".ruff_cache", ".pytest_cache", ".hmx-ls"}
REVERSE_SKIP = {"+", ""}
_ROOT = ""


@dataclass
class ModelEntry:
    declared: dict[str, Loc] = field(default_factory=dict)
    injected: dict[str, Loc] = field(default_factory=dict)
    reverse: dict[str, Loc] = field(default_factory=dict)
    comodel: dict[str, str] = field(default_factory=dict)
    edges: set[str] = field(default_factory=set)
    sites: list[Loc] = field(default_factory=list)
    methods: dict[str, Loc] = field(default_factory=dict)


@dataclass
class Index:
    models: dict[str, ModelEntry] = field(default_factory=dict)
    modules: dict[str, Module] = field(default_factory=dict)
    xmlids: XmlIdIndex = field(default_factory=XmlIdIndex)
    webx: WebxIndex = field(default_factory=WebxIndex)
    routes: RoutesIndex = field(default_factory=RoutesIndex)
    security: SecurityIndex = field(default_factory=SecurityIndex)
    file_models: dict[str, list[str]] = field(default_factory=dict)
    root: str = ""

    def entry(self, model: str) -> ModelEntry:
        got = self.models.get(model)
        if got is None:
            got = ModelEntry()
            self.models[model] = got
        return got

    def known(self, model: str) -> bool:
        return model in self.models

    def update_file(self, rel_path: str, content: bytes) -> set[str]:
        affected_models: set[str] = set()
        if rel_path.endswith(".py"):
            mod = owner_of(rel_path)
            try:
                decls, _ = extract(content, rel_path, mod)
            except (SyntaxError, OSError):
                return affected_models
            old_models = self.file_models.get(rel_path, [])
            affected_models.update(old_models)
            for m in old_models:
                if m in self.models:
                    self.models[m].sites = [s for s in self.models[m].sites if s.path != rel_path]
                    self.models[m].declared = {k: v for k, v in self.models[m].declared.items() if v.path != rel_path}
                    self.models[m].methods = {k: v for k, v in self.models[m].methods.items() if v.path != rel_path}
            new_models = []
            for d in decls:
                entry = self.entry(d.model)
                entry.sites.append(d.loc)
                new_models.append(d.model)
                affected_models.add(d.model)
                for m_name, m_loc in d.methods.items():
                    entry.methods[m_name] = m_loc
                for fd in d.fields:
                    entry.declared[fd.name] = fd.loc
                    if fd.comodel:
                        entry.comodel[fd.name] = fd.comodel
            self.file_models[rel_path] = new_models
        elif rel_path.endswith(".xml"):
            try:
                tree = etree.fromstring(content)
                mod = owner_of(rel_path)
                entries = extract_xmlids_from_tree(tree, rel_path, mod)
                old_ids = self.xmlids.by_file.get(rel_path, [])
                for oid in old_ids:
                    self.xmlids.entries.pop(oid, None)
                new_ids = []
                for e in entries:
                    self.xmlids.entries[e.xmlid] = e
                    new_ids.append(e.xmlid)
                self.xmlids.by_file[rel_path] = new_ids
            except (etree.XMLSyntaxError, OSError):
                pass
        return affected_models


def python_files(root: str) -> list[str]:
    out = []
    base = os.path.join(root, "hmx")
    if not os.path.isdir(base):
        return out
    for parent, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [os.path.join(parent, n) for n in names if n.endswith(".py")]
    return out


def xml_files(root: str) -> list[str]:
    out = []
    base = os.path.join(root, "hmx", "module")
    if not os.path.isdir(base):
        return out
    for parent, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [os.path.join(parent, n) for n in names if n.endswith(".xml")]
    return out


def scan(paths: list[str]) -> tuple[list[ClassDecl], set[str]]:
    out: list[ClassDecl] = []
    factories: set[str] = set()
    for path in paths:
        rel = os.path.relpath(path, _ROOT)
        try:
            decls, found = extract(open(path, "rb").read(), rel, owner_of(rel))
        except (SyntaxError, OSError):
            continue
        out += decls
        factories |= found
    return out, factories


def _init(root: str) -> None:
    global _ROOT
    _ROOT = root


def _context():
    methods = multiprocessing.get_all_start_methods()
    return multiprocessing.get_context("fork" if "fork" in methods else "spawn")


def keep_model_classes(decls: list[ClassDecl]) -> list[ClassDecl]:
    by_name: dict[str, list[ClassDecl]] = {}
    for decl in decls:
        by_name.setdefault(decl.class_name, []).append(decl)
    verdict: dict[str, bool] = {}

    def is_model(name: str, stack: frozenset[str]) -> bool:
        if name in verdict:
            return verdict[name]
        if name in stack or name not in by_name:
            return False
        found = any(d.direct_model or d.django_user or
                    any(is_model(b, stack | {name}) for b in d.bases)
                    for d in by_name[name])
        verdict[name] = found
        return found

    return [d for d in decls if d.direct_model or d.django_user or is_model(d.class_name, frozenset())]


def apply_class_edges(decls: list[ClassDecl]) -> None:
    model_of: dict[str, set[str]] = {}
    for decl in decls:
        model_of.setdefault(decl.class_name, set()).add(decl.model)
    for decl in decls:
        for base in decl.bases:
            for parent in model_of.get(base, ()):
                if parent != decl.model:
                    decl.parents.append(parent)


def promote_factories(decls: list[ClassDecl], factories: set[str]) -> None:
    for decl in decls:
        for pending in decl.pending:
            if pending.callee in factories:
                decl.fields.append(pending.decl)


def assemble(decls: list[ClassDecl], modules: dict[str, Module],
             factories: set[str] | None = None) -> Index:
    decls = keep_model_classes(decls)
    promote_factories(decls, factories or set())
    apply_class_edges(decls)
    index = Index(modules=modules)
    for decl in decls:
        entry = index.entry(decl.model)
        entry.sites.append(decl.loc)
        entry.edges |= set(decl.parents) | set(decl.delegates)
        index.file_models.setdefault(decl.loc.path, []).append(decl.model)
        for m_name, m_loc in decl.methods.items():
            entry.methods.setdefault(m_name, m_loc)
        active = modules[decl.module].active_rule if decl.module in modules else False
        if decl.django_user:
            for name in DJANGO_USER_FIELDS:
                entry.declared.setdefault(name, decl.loc)
        for name in EXTERNAL_BASE_FIELDS.get(decl.model, ()):
            entry.injected.setdefault(name, decl.loc)
        for name, (loc, comodel) in injected(decl, active).items():
            entry.injected.setdefault(name, loc)
            if comodel:
                entry.comodel.setdefault(name, comodel)
        for fd in decl.fields:
            entry.declared.setdefault(fd.name, fd.loc)
            if fd.comodel:
                entry.comodel.setdefault(fd.name, fd.comodel)
                if fd.related_name and fd.related_name not in REVERSE_SKIP:
                    target = index.entry(fd.comodel)
                    target.reverse.setdefault(fd.related_name, fd.loc)
                    target.comodel.setdefault(fd.related_name, decl.model)
    return index


def build(root: str, workers: int | None = None) -> Index:
    global _ROOT
    root = os.path.abspath(root)
    _ROOT = root
    modules = discover(root)
    py_paths = python_files(root)
    xml_paths = xml_files(root)
    workers = workers or os.cpu_count() or 4
    decls: list[ClassDecl] = []
    factories: set[str] = set()
    if workers > 1:
        chunks = [py_paths[i::workers] for i in range(workers)]
        with ProcessPoolExecutor(max_workers=workers, mp_context=_context(),
                                 initializer=_init, initargs=(root,)) as pool:
            for part, found in pool.map(scan, chunks):
                decls += part
                factories |= found
    else:
        decls, factories = scan(py_paths)

    index = assemble(decls, modules, factories)
    index.root = root
    index.xmlids = scan_xmlids(xml_paths, root)
    index.webx = scan_webx(root)
    index.routes = scan_routes(root, py_paths)
    index.security = scan_security(root)
    return index
