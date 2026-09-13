from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

from lxml import etree

from .injection import DJANGO_USER_FIELDS, EXTERNAL_BASE_FIELDS, injected
from .locations import Loc
from .manifest import Module, discover, owner_of
from .pysource import ClassDecl, computes_of, extract, kinds_of, selections_of
from .assets import AssetIndex, scan_assets
from .records import RecordsIndex, extract_records_from_tree, scan_records
from .routes import RoutesIndex, scan_routes
from .security import SecurityIndex, scan_security
from .webx import WebxIndex, scan_webx
from .xmlids import XmlIdIndex, extract_xmlids_from_tree, scan_xmlids

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
    kinds: dict[str, str] = field(default_factory=dict)
    selections: dict[str, list[str]] = field(default_factory=dict)
    computes: dict[str, str] = field(default_factory=dict)
    ordering: list[str] = field(default_factory=list)
    rec_name: str | None = None


@dataclass
class Index:
    models: dict[str, ModelEntry] = field(default_factory=dict)
    modules: dict[str, Module] = field(default_factory=dict)
    xmlids: XmlIdIndex = field(default_factory=XmlIdIndex)
    webx: WebxIndex = field(default_factory=WebxIndex)
    routes: RoutesIndex = field(default_factory=RoutesIndex)
    security: SecurityIndex = field(default_factory=SecurityIndex)
    records: RecordsIndex = field(default_factory=RecordsIndex)
    assets: AssetIndex = field(default_factory=AssetIndex)
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
        affected: set[str] = set()
        if os.path.basename(rel_path) == "__hmx__.py":
            self.assets.update_file(rel_path, os.path.join(self.root, rel_path))
        if rel_path.endswith(".py"):
            mod = owner_of(rel_path)
            try:
                decls, _ = extract(content, rel_path, mod)
            except (SyntaxError, OSError, ValueError):
                return affected
            for stale in self.file_models.get(rel_path, []):
                affected.add(stale)
                got = self.models.get(stale)
                if got is None:
                    continue
                got.sites = [s for s in got.sites if s.path != rel_path]
                got.declared = {k: v for k, v in got.declared.items() if v.path != rel_path}
                got.methods = {k: v for k, v in got.methods.items() if v.path != rel_path}
            fresh: list[str] = []
            for decl in decls:
                entry = self.entry(decl.model)
                entry.sites.append(decl.loc)
                fresh.append(decl.model)
                affected.add(decl.model)
                entry.edges |= set(decl.parents) | set(decl.delegates)
                entry.methods.update(decl.methods)
                entry.kinds.update(kinds_of(decl))
                entry.selections.update(selections_of(decl))
                entry.computes.update(computes_of(decl))
                if decl.ordering:
                    entry.ordering = list(decl.ordering)
                if decl.rec_name:
                    entry.rec_name = decl.rec_name
                for fd in decl.fields:
                    entry.declared[fd.name] = fd.loc
                    if fd.comodel:
                        entry.comodel[fd.name] = fd.comodel
            self.file_models[rel_path] = fresh
        elif rel_path.endswith(".xml"):
            try:
                tree = etree.fromstring(content)
            except (etree.XMLSyntaxError, ValueError):
                return affected
            mod = owner_of(rel_path)
            for stale in self.xmlids.by_file.get(rel_path, []):
                self.xmlids.entries.pop(stale, None)
            fresh_ids: list[str] = []
            for xentry in extract_xmlids_from_tree(tree, rel_path, mod):
                self.xmlids.entries[xentry.xmlid] = xentry
                fresh_ids.append(xentry.xmlid)
            self.xmlids.by_file[rel_path] = fresh_ids
            self._merge_records(rel_path, tree, mod)
        elif rel_path.endswith((".js", ".vue")):
            self.webx.update_file(rel_path, os.path.join(self.root, rel_path))
        elif rel_path.endswith(".csv") and "security" in rel_path:
            self.security.update_file(rel_path, os.path.join(self.root, rel_path),
                                      owner_of(rel_path))
        return affected

    def _merge_records(self, rel_path: str, tree, module: str | None) -> None:
        try:
            fresh = extract_records_from_tree(tree, rel_path, module)
        except Exception:
            return
        for stale in self.records.by_file.get(rel_path, []):
            for bucket in (self.records.actions, self.records.rules, self.records.groups,
                           self.records.menus, self.records.crons, self.records.reports,
                           self.records.sequences):
                bucket.pop(stale, None)
        self.records.actions.update(fresh.actions)
        self.records.rules.update(fresh.rules)
        self.records.groups.update(fresh.groups)
        self.records.menus.update(fresh.menus)
        self.records.crons.update(fresh.crons)
        self.records.reports.update(fresh.reports)
        self.records.sequences.update(fresh.sequences)
        for model, xmlids in fresh.by_model.items():
            existing = self.records.by_model.setdefault(model, [])
            for xmlid in xmlids:
                if xmlid not in existing:
                    existing.append(xmlid)
        self.records.by_file[rel_path] = fresh.by_file.get(rel_path, [])


def python_files(root: str) -> list[str]:
    out: list[str] = []
    base = os.path.join(root, "hmx")
    if not os.path.isdir(base):
        return out
    for parent, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [os.path.join(parent, n) for n in names if n.endswith(".py")]
    return out


def xml_files(root: str) -> list[str]:
    out: list[str] = []
    base = os.path.join(root, "hmx", "module")
    if not os.path.isdir(base):
        return out
    for parent, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        out += [os.path.join(parent, n) for n in names if n.endswith(".xml")]
    return out


INDEXED_SUFFIXES = (".py", ".xml", ".js", ".vue", ".csv", ".css", ".scss")
DIGEST_SKIP_DIRS = SKIP_DIRS - {"static"}


def indexed_files(root: str) -> list[str]:
    out: list[str] = []
    base = os.path.join(root, "hmx")
    if not os.path.isdir(base):
        return out
    for parent, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in DIGEST_SKIP_DIRS]
        out += [os.path.join(parent, n) for n in names
                if n.endswith(INDEXED_SUFFIXES)]
    return out


def scan(paths: list[str]) -> tuple[list[ClassDecl], set[str]]:
    out: list[ClassDecl] = []
    factories: set[str] = set()
    for path in paths:
        rel = os.path.relpath(path, _ROOT)
        try:
            decls, found = extract(open(path, "rb").read(), rel, owner_of(rel))
        except (SyntaxError, OSError, ValueError):
            continue
        out += decls
        factories |= found
    return out, factories


def _init(root: str) -> None:
    global _ROOT
    _ROOT = root


def _context():
    methods = multiprocessing.get_all_start_methods()
    for method in ("forkserver", "spawn"):
        if method in methods:
            return multiprocessing.get_context(method)
    return multiprocessing.get_context()


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

    return [d for d in decls
            if d.direct_model or d.django_user or is_model(d.class_name, frozenset())]


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
        for name, loc in decl.methods.items():
            entry.methods.setdefault(name, loc)
        for name, kind in kinds_of(decl).items():
            entry.kinds.setdefault(name, kind)
        for name, choices in selections_of(decl).items():
            entry.selections.setdefault(name, choices)
        for name, method in computes_of(decl).items():
            entry.computes.setdefault(name, method)
        if decl.ordering and not entry.ordering:
            entry.ordering = list(decl.ordering)
        if decl.rec_name and entry.rec_name is None:
            entry.rec_name = decl.rec_name
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
    if workers > 1 and len(py_paths) > workers:
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
    index.records = scan_records(xml_paths, root)
    index.webx = scan_webx(root)
    index.routes = scan_routes(root, py_paths)
    index.security = scan_security(root)
    index.assets = scan_assets(root)
    return index
