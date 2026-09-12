from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from lxml import etree

from .locations import Loc
from .manifest import owner_of
from .xmlids import qualify_xmlid

_REF_RE = re.compile(r"""\bref\s*\(\s*(['\"])([^'\"]+)\1\s*\)""")

ACTION_MODELS = {
    "baseactionactwindow": "act_window",
    "baseactionactwindowview": "act_window_view",
    "baseactionclient": "client",
    "baseactionserver": "server",
    "baseactionreport": "report",
}

RULE_MODEL = "baserule"
GROUP_MODEL = "group"
MENU_MODEL = "baseuimenu"
SEQUENCE_MODEL = "basesequence"
REPORT_MODEL = "baseactionreport"

MODEL_FIELDS = ("res_model", "model", "model_id", "binding_model")
RULE_MODEL_FIELDS = ("model", "model_id")
PARENT_FIELDS = ("parent", "parent_id")
ACTION_FIELDS = ("action", "action_id")
IMPLIED_FIELDS = ("implieds", "implied_ids", "implied")
CATEGORY_FIELDS = ("category", "category_id")


@dataclass
class ActionEntry:
    xmlid: str
    kind: str
    res_model: str | None
    tag: str | None
    domain: str | None
    context: str | None
    view_mode: str | None
    groups: list[str]
    loc: Loc


@dataclass
class RuleEntry:
    xmlid: str
    model: str | None
    domain_force: str | None
    groups: list[str]
    is_global: bool
    loc: Loc


@dataclass
class GroupEntry:
    xmlid: str
    name: str | None
    category: str | None
    implied: list[str]
    loc: Loc


@dataclass
class MenuEntry:
    xmlid: str
    name: str | None
    parent: str | None
    action: str | None
    groups: list[str]
    sequence: int | None
    web_icon: str | None
    loc: Loc


@dataclass
class RecordsIndex:
    actions: dict[str, ActionEntry] = field(default_factory=dict)
    rules: dict[str, RuleEntry] = field(default_factory=dict)
    groups: dict[str, GroupEntry] = field(default_factory=dict)
    menus: dict[str, MenuEntry] = field(default_factory=dict)
    crons: dict[str, Loc] = field(default_factory=dict)
    reports: dict[str, Loc] = field(default_factory=dict)
    sequences: dict[str, Loc] = field(default_factory=dict)
    by_model: dict[str, list[str]] = field(default_factory=dict)
    by_file: dict[str, list[str]] = field(default_factory=dict)

    def action(self, xmlid: str, module: str | None = None) -> ActionEntry | None:
        return _lookup(self.actions, xmlid, module)

    def group(self, xmlid: str, module: str | None = None) -> GroupEntry | None:
        return _lookup(self.groups, xmlid, module)

    def menu(self, xmlid: str, module: str | None = None) -> MenuEntry | None:
        return _lookup(self.menus, xmlid, module)

    def rules_for_model(self, model: str) -> list[RuleEntry]:
        if not model:
            return []
        key = model.split(".")[-1].lower()
        out: list[RuleEntry] = []
        for xmlid in self.by_model.get(key, []):
            entry = self.rules.get(xmlid)
            if entry is not None:
                out.append(entry)
        return out

    def menu_children(self, xmlid: str) -> list[MenuEntry]:
        if not xmlid:
            return []
        bare = xmlid.split(".")[-1]
        out: list[MenuEntry] = []
        for entry in self.menus.values():
            parent = entry.parent
            if not parent:
                continue
            if parent == xmlid or parent.split(".")[-1] == bare:
                out.append(entry)
        out.sort(key=lambda e: (e.sequence if e.sequence is not None else 10 ** 6, e.xmlid))
        return out


def _lookup(store: dict, xmlid: str, module: str | None):
    if not xmlid:
        return None
    entry = store.get(xmlid)
    if entry is not None:
        return entry
    if module and "." not in xmlid:
        return store.get(f"{module}.{xmlid}")
    return None


def _absorb(old, new):
    if old is None:
        return new
    for name, value in list(vars(new).items()):
        if name in ("xmlid", "loc"):
            continue
        if value is None or value == "" or value == []:
            setattr(new, name, getattr(old, name, value))
    return new


def _store(store: dict, entry) -> None:
    store[entry.xmlid] = _absorb(store.get(entry.xmlid), entry)


def _text(elem) -> str | None:
    if elem is None:
        return None
    value = (elem.text or "").strip()
    return value or None


def _direct_fields(elem) -> dict:
    out: dict = {}
    for child in elem:
        if not isinstance(child.tag, str) or child.tag != "field":
            continue
        name = child.get("name")
        if name and name not in out:
            out[name] = child
    return out


def _field_value(fields: dict, *names: str) -> str | None:
    for name in names:
        child = fields.get(name)
        if child is None:
            continue
        value = _text(child)
        if value:
            return value
        for attr in ("ref", "eval"):
            raw = child.get(attr)
            if raw and raw.strip():
                return raw.strip()
    return None


def _field_xmlid(fields: dict, module: str | None, *names: str) -> str | None:
    for name in names:
        child = fields.get(name)
        if child is None:
            continue
        raw = child.get("ref") or _text(child)
        if raw:
            return qualify_xmlid(raw.strip(), module)
    return None


def _normalize_model(raw: str | None, via_ref: bool) -> str | None:
    if not raw:
        return None
    name = raw.split(".")[-1].strip().lower()
    if via_ref and name.startswith("model_") and len(name) > 6:
        name = name[6:]
    return name or None


def _model_of(fields: dict, names: tuple[str, ...]) -> str | None:
    for name in names:
        child = fields.get(name)
        if child is None:
            continue
        raw = _text(child)
        if raw:
            return _normalize_model(raw, False)
        ref = child.get("ref")
        if ref and ref.strip():
            return _normalize_model(ref.strip(), True)
    return None


def _eval_refs(fields: dict, module: str | None, *names: str) -> list[str]:
    out: list[str] = []
    for name in names:
        child = fields.get(name)
        if child is None:
            continue
        raw = child.get("eval") or _text(child) or ""
        for m in _REF_RE.finditer(raw):
            qid = qualify_xmlid(m.group(2).strip(), module)
            if qid and qid not in out:
                out.append(qid)
    return out


def _split_xmlids(raw: str | None, module: str | None) -> list[str]:
    out: list[str] = []
    for chunk in (raw or "").split(","):
        text = chunk.strip()
        if text.startswith("!"):
            text = text[1:].strip()
        if not text:
            continue
        qid = qualify_xmlid(text, module)
        if qid not in out:
            out.append(qid)
    return out


def _truthy(raw: str | None) -> bool:
    if raw is None:
        return False
    return raw.strip().lower() in ("1", "true", "yes")


def _int_or_none(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _register(idx: RecordsIndex, rel_path: str, xmlid: str, model: str | None) -> None:
    idx.by_file.setdefault(rel_path, []).append(xmlid)
    if model:
        bucket = idx.by_model.setdefault(model, [])
        if xmlid not in bucket:
            bucket.append(xmlid)


def _action_from_record(fields: dict, qid: str, kind: str, module: str | None, loc: Loc) -> ActionEntry:
    return ActionEntry(
        xmlid=qid,
        kind=kind,
        res_model=_model_of(fields, MODEL_FIELDS),
        tag=_field_value(fields, "tag"),
        domain=_field_value(fields, "domain"),
        context=_field_value(fields, "context"),
        view_mode=_field_value(fields, "view_mode", "view_type"),
        groups=_eval_refs(fields, module, "groups", "groups_id"),
        loc=loc,
    )


def _menu_from_record(fields: dict, qid: str, module: str | None, loc: Loc) -> MenuEntry:
    return MenuEntry(
        xmlid=qid,
        name=_field_value(fields, "name"),
        parent=_field_xmlid(fields, module, *PARENT_FIELDS),
        action=_field_xmlid(fields, module, *ACTION_FIELDS),
        groups=_eval_refs(fields, module, "groups", "groups_id"),
        sequence=_int_or_none(_field_value(fields, "sequence")),
        web_icon=_field_value(fields, "web_icon"),
        loc=loc,
    )


def _menu_from_element(elem, qid: str, module: str | None, loc: Loc) -> MenuEntry:
    parent = elem.get("parent")
    action = elem.get("action")
    return MenuEntry(
        xmlid=qid,
        name=elem.get("name"),
        parent=qualify_xmlid(parent.strip(), module) if parent else None,
        action=qualify_xmlid(action.strip(), module) if action else None,
        groups=_split_xmlids(elem.get("groups"), module),
        sequence=_int_or_none(elem.get("sequence")),
        web_icon=elem.get("web_icon"),
        loc=loc,
    )


def extract_records_from_tree(tree, rel_path: str, module: str | None) -> RecordsIndex:
    idx = RecordsIndex()
    if tree is None:
        return idx
    try:
        walker = tree.iter()
    except (AttributeError, TypeError):
        return idx
    for elem in walker:
        tag = elem.tag
        if not isinstance(tag, str):
            continue
        if tag not in ("record", "menuitem"):
            continue
        raw_id = elem.get("id")
        if not raw_id:
            continue
        qid = qualify_xmlid(raw_id.strip(), module)
        if not qid:
            continue
        loc = Loc(rel_path, elem.sourceline or 1, 0)
        if tag == "menuitem":
            _store(idx.menus, _menu_from_element(elem, qid, module, loc))
            _register(idx, rel_path, qid, None)
            continue
        model = (elem.get("model") or "").strip()
        if not model:
            continue
        fields = _direct_fields(elem)
        kind = ACTION_MODELS.get(model)
        if kind is not None:
            entry = _action_from_record(fields, qid, kind, module, loc)
            _store(idx.actions, entry)
            _register(idx, rel_path, qid, entry.res_model)
            if model == REPORT_MODEL:
                idx.reports[qid] = loc
            continue
        if model == RULE_MODEL:
            groups = _eval_refs(fields, module, "groups", "groups_id")
            global_field = fields.get("global")
            if global_field is not None:
                is_global = _truthy(global_field.get("eval") or _text(global_field))
            else:
                is_global = not groups
            entry_rule = RuleEntry(
                xmlid=qid,
                model=_model_of(fields, RULE_MODEL_FIELDS),
                domain_force=_field_value(fields, "domain_force", "domain"),
                groups=groups,
                is_global=is_global,
                loc=loc,
            )
            _store(idx.rules, entry_rule)
            _register(idx, rel_path, qid, entry_rule.model)
            continue
        if model == GROUP_MODEL:
            _store(idx.groups, GroupEntry(
                xmlid=qid,
                name=_field_value(fields, "name"),
                category=_field_xmlid(fields, module, *CATEGORY_FIELDS),
                implied=_eval_refs(fields, module, *IMPLIED_FIELDS),
                loc=loc,
            ))
            _register(idx, rel_path, qid, None)
            continue
        if model == MENU_MODEL:
            _store(idx.menus, _menu_from_record(fields, qid, module, loc))
            _register(idx, rel_path, qid, None)
            continue
        if model == SEQUENCE_MODEL:
            idx.sequences[qid] = loc
            _register(idx, rel_path, qid, None)
            continue
        if "cron" in model.lower():
            idx.crons[qid] = loc
            _register(idx, rel_path, qid, None)
    return idx


def extract_records_from_file(path: str, rel_path: str, module: str | None) -> RecordsIndex:
    try:
        tree = etree.parse(path)
    except (etree.XMLSyntaxError, OSError, ValueError):
        return RecordsIndex()
    return extract_records_from_tree(tree, rel_path, module)


def _merge(target: RecordsIndex, source: RecordsIndex) -> None:
    for entry in source.actions.values():
        _store(target.actions, entry)
    for entry in source.rules.values():
        _store(target.rules, entry)
    for entry in source.groups.values():
        _store(target.groups, entry)
    for entry in source.menus.values():
        _store(target.menus, entry)
    target.crons.update(source.crons)
    target.reports.update(source.reports)
    target.sequences.update(source.sequences)
    for model, xmlids in source.by_model.items():
        bucket = target.by_model.setdefault(model, [])
        for xmlid in xmlids:
            if xmlid not in bucket:
                bucket.append(xmlid)
    for rel, xmlids in source.by_file.items():
        target.by_file[rel] = xmlids


def scan_records(xml_paths: list[str], root: str) -> RecordsIndex:
    idx = RecordsIndex()
    for path in xml_paths:
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            rel = path
        rel = rel.replace(os.sep, "/")
        found = extract_records_from_file(path, rel, owner_of(rel))
        if found.by_file:
            _merge(idx, found)
    return idx
