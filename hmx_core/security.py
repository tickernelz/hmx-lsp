from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field

from .locations import Loc
from .manifest import owner_of


@dataclass
class AclEntry:
    acl_id: str
    name: str
    raw_model_id: str
    model: str
    group_xmlid: str | None
    loc: Loc
    perms: tuple[bool, bool, bool, bool]


@dataclass
class SecurityIndex:
    by_model: dict[str, list[AclEntry]] = field(default_factory=dict)
    by_group: dict[str, list[AclEntry]] = field(default_factory=dict)
    by_file: dict[str, list[AclEntry]] = field(default_factory=dict)

    def acls_for_model(self, model: str) -> list[AclEntry]:
        norm = model.lower().replace(".", "").replace("_", "")
        return self.by_model.get(norm, [])

    def acls_for_group(self, group_xmlid: str) -> list[AclEntry]:
        return self.by_group.get(group_xmlid, [])


def normalize_model_id(raw: str) -> str:
    cleaned = raw.strip()
    token = cleaned.split(".")[-1]
    if token.startswith("model_"):
        token = token[6:]
    return token.lower().replace("_", "")


def extract_acls_from_csv(path: str, rel_path: str, module: str | None) -> list[AclEntry]:
    out: list[AclEntry] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            reader = csv.reader(fh)
            header = None
            for row_num, row in enumerate(reader, start=1):
                if not row or not any(row):
                    continue
                if header is None:
                    header = [c.strip().lower() for c in row]
                    continue
                if len(row) < 8:
                    continue
                acl_id = row[0].strip()
                name = row[1].strip()
                model_col = row[2].strip()
                group_col = row[3].strip() or None
                if group_col and "." not in group_col and module:
                    group_col = f"{module}.{group_col}"
                try:
                    perms = (bool(int(row[4])), bool(int(row[5])),
                             bool(int(row[6])), bool(int(row[7])))
                except (ValueError, IndexError):
                    perms = (False, False, False, False)

                norm_model = normalize_model_id(model_col)
                loc = Loc(rel_path, row_num, 0)
                out.append(AclEntry(acl_id=acl_id, name=name, raw_model_id=model_col,
                                    model=norm_model, group_xmlid=group_col, loc=loc,
                                    perms=perms))
    except OSError:
        return out
    return out


def scan_security(root: str) -> SecurityIndex:
    idx = SecurityIndex()
    module_dir = os.path.join(root, "hmx", "module")
    if not os.path.isdir(module_dir):
        return idx

    for dirpath, _, filenames in os.walk(module_dir):
        if any(s in dirpath for s in (".git", "node_modules", "__pycache__")):
            continue
        for f in filenames:
            if f.endswith(".csv"):
                path = os.path.join(dirpath, f)
                rel = os.path.relpath(path, root)
                mod = owner_of(rel)
                entries = extract_acls_from_csv(path, rel, mod)
                if entries:
                    idx.by_file[rel] = entries
                    for e in entries:
                        idx.by_model.setdefault(e.model, []).append(e)
                        if e.group_xmlid:
                            idx.by_group.setdefault(e.group_xmlid, []).append(e)

    return idx
