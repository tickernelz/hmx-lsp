from __future__ import annotations

from .index import Index
from .locations import Loc


class Resolver:
    def __init__(self, index: Index):
        self.index = index
        self._fields: dict[str, dict[str, Loc]] = {}
        self._methods: dict[str, dict[str, Loc]] = {}
        self._comodel: dict[tuple[str, str], str | None] = {}
        self._selections: dict[str, dict[str, list[str]]] = {}
        self._computes: dict[str, dict[str, str]] = {}
        self._kinds: dict[str, dict[str, str]] = {}
        self._mro: dict[str, list[str]] = {}
        self._method_result_models: dict[tuple[str, str], str | None] = {}

    def known(self, model: str) -> bool:
        return self.index.known(model)

    def invalidate(self, models: set[str] | None = None) -> None:
        self._method_result_models.clear()
        if not models:
            self._fields.clear()
            self._methods.clear()
            self._comodel.clear()
            self._selections.clear()
            self._computes.clear()
            self._kinds.clear()
            self._mro.clear()
            return
        for m in models:
            self._fields.pop(m, None)
            self._methods.pop(m, None)
            self._selections.pop(m, None)
            self._computes.pop(m, None)
            self._kinds.pop(m, None)
            self._mro.pop(m, None)
        self._comodel = {k: v for k, v in self._comodel.items() if k[0] not in models}

    def fields(self, model: str, _seen: frozenset[str] = frozenset()) -> dict[str, Loc]:
        cached = self._fields.get(model)
        if cached is not None:
            return cached
        entry = self.index.models.get(model)
        if entry is None or model in _seen:
            return {}
        seen = _seen | {model}
        out = dict(entry.declared)
        for source in (entry.reverse, entry.injected):
            for name, loc in source.items():
                out.setdefault(name, loc)
        for parent in sorted(entry.edges):
            for name, loc in self.fields(parent, seen).items():
                out.setdefault(name, loc)
        if not _seen:
            self._fields[model] = out
        return out

    def methods(self, model: str, _seen: frozenset[str] = frozenset()) -> dict[str, Loc]:
        cached = self._methods.get(model)
        if cached is not None:
            return cached
        entry = self.index.models.get(model)
        if entry is None or model in _seen:
            return {}
        seen = _seen | {model}
        out = dict(entry.methods)
        for parent in sorted(entry.edges):
            for name, loc in self.methods(parent, seen).items():
                out.setdefault(name, loc)
        if not _seen:
            self._methods[model] = out
        return out

    def comodel(self, model: str, name: str, _seen: frozenset[str] = frozenset()) -> str | None:
        key = (model, name)
        if key in self._comodel:
            return self._comodel[key]
        entry = self.index.models.get(model)
        if entry is None or model in _seen:
            return None
        found = entry.comodel.get(name)
        if found is None:
            for parent in sorted(entry.edges):
                found = self.comodel(parent, name, _seen | {model})
                if found:
                    break
        self._comodel[key] = found
        return found

    def selections(self, model: str, _seen: frozenset[str] = frozenset()) -> dict[str, list[str]]:
        cached = self._selections.get(model)
        if cached is not None:
            return cached
        entry = self.index.models.get(model)
        if entry is None or model in _seen:
            return {}
        seen = _seen | {model}
        out = {name: list(values)
               for name, values in getattr(entry, "selections", {}).items()}
        for parent in sorted(entry.edges):
            for name, values in self.selections(parent, seen).items():
                out.setdefault(name, list(values))
        if not _seen:
            self._selections[model] = out
        return out

    def computes(self, model: str, _seen: frozenset[str] = frozenset()) -> dict[str, str]:
        cached = self._computes.get(model)
        if cached is not None:
            return cached
        entry = self.index.models.get(model)
        if entry is None or model in _seen:
            return {}
        seen = _seen | {model}
        out = dict(getattr(entry, "computes", {}))
        for parent in sorted(entry.edges):
            for name, method in self.computes(parent, seen).items():
                out.setdefault(name, method)
        if not _seen:
            self._computes[model] = out
        return out

    def kinds(self, model: str, _seen: frozenset[str] = frozenset()) -> dict[str, str]:
        cached = self._kinds.get(model)
        if cached is not None:
            return cached
        entry = self.index.models.get(model)
        if entry is None or model in _seen:
            return {}
        seen = _seen | {model}
        out = dict(getattr(entry, "kinds", {}))
        for parent in sorted(entry.edges):
            for name, kind in self.kinds(parent, seen).items():
                out.setdefault(name, kind)
        if not _seen:
            self._kinds[model] = out
        return out

    def field_kind(self, model: str, name: str) -> str | None:
        return self.kinds(model).get(name)

    def mro(self, model: str, _seen: frozenset[str] = frozenset()) -> list[str]:
        cached = self._mro.get(model)
        if cached is not None:
            return cached
        entry = self.index.models.get(model)
        if entry is None or model in _seen:
            return []
        seen = _seen | {model}
        out = [model]
        for parent in sorted(entry.edges):
            for name in self.mro(parent, seen):
                if name not in out:
                    out.append(name)
        if not _seen:
            self._mro[model] = out
        return out

    def resolve_path(self, model: str, dotted: str) -> list[tuple[str, str, Loc | None]]:
        out: list[tuple[str, str, Loc | None]] = []
        current = model
        for hop in dotted.split("."):
            if not current or not hop:
                break
            table = self.fields(current)
            if hop not in table:
                break
            out.append((current, hop, table[hop]))
            current = self.comodel(current, hop) or ""
        return out
