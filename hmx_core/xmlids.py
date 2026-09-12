from __future__ import annotations

import os
from dataclasses import dataclass, field
from lxml import etree

from .locations import Loc
from .manifest import owner_of


@dataclass
class XmlIdEntry:
    xmlid: str
    model: str | None
    name: str | None
    loc: Loc
    noupdate: bool = False
    action: str | None = None
    parent: str | None = None


@dataclass
class XmlIdIndex:
    entries: dict[str, XmlIdEntry] = field(default_factory=dict)
    by_file: dict[str, list[str]] = field(default_factory=dict)
    models: dict[str, list[str]] = field(default_factory=dict)

    def get(self, xmlid: str, default_module: str | None = None) -> XmlIdEntry | None:
        entry = self.entries.get(xmlid)
        if entry is not None:
            return entry
        if default_module and "." not in xmlid:
            return self.entries.get(f"{default_module}.{xmlid}")
        return None

    def resolve_ref(self, ref: str, current_module: str | None = None) -> Loc | None:
        entry = self.get(ref, current_module)
        return entry.loc if entry else None


def qualify_xmlid(raw_id: str, module: str | None) -> str:
    if not raw_id:
        return ""
    if "." in raw_id or not module:
        return raw_id
    return f"{module}.{raw_id}"


def extract_xmlids_from_file(path: str, rel_path: str, module: str | None) -> list[XmlIdEntry]:
    try:
        tree = etree.parse(path)
    except (etree.XMLSyntaxError, OSError):
        return []
    return extract_xmlids_from_tree(tree, rel_path, module)


def extract_xmlids_from_tree(tree, rel_path: str, module: str | None) -> list[XmlIdEntry]:
    out: list[XmlIdEntry] = []
    for elem in tree.iter():
        tag = elem.tag
        if not isinstance(tag, str):
            continue
        raw_id = elem.get("id")
        if not raw_id:
            continue
        qid = qualify_xmlid(raw_id, module)
        line = elem.sourceline or 1
        loc = Loc(rel_path, line, 0)
        if tag == "record":
            model = elem.get("model")
            name = None
            for f in elem:
                if isinstance(f.tag, str) and f.tag == "field" and f.get("name") == "name":
                    name = (f.text or "").strip() or None
                    break
            out.append(XmlIdEntry(xmlid=qid, model=model, name=name, loc=loc))
        elif tag == "menuitem":
            action = elem.get("action")
            parent = elem.get("parent")
            name = elem.get("name")
            out.append(XmlIdEntry(xmlid=qid, model="baseuimenu", name=name, loc=loc,
                                  action=action, parent=parent))
        elif tag == "template":
            out.append(XmlIdEntry(xmlid=qid, model="baseuiview", name=qid, loc=loc))
    return out


def scan_xmlids(xml_paths: list[str], root: str) -> XmlIdIndex:
    idx = XmlIdIndex()
    for path in xml_paths:
        rel = os.path.relpath(path, root)
        mod = owner_of(rel)
        entries = extract_xmlids_from_file(path, rel, mod)
        if entries:
            file_ids: list[str] = []
            for e in entries:
                idx.entries[e.xmlid] = e
                file_ids.append(e.xmlid)
                if e.model:
                    idx.models.setdefault(e.model, []).append(e.xmlid)
            idx.by_file[rel] = file_ids
    return idx
