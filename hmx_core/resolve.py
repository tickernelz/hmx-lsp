from __future__ import annotations

from .index import Index
from .locations import Loc


class Resolver:
    def __init__(self, index: Index):
        self.index = index
        self._fields: dict[str, dict[str, Loc]] = {}
        self._methods: dict[str, dict[str, Loc]] = {}
        self._comodel: dict[tuple[str, str], str | None] = {}

    def known(self, model: str) -> bool:
        return self.index.known(model)

    def invalidate(self, models: set[str] | None = None) -> None:
        if not models:
            self._fields.clear()
            self._methods.clear()
            self._comodel.clear()
            return
        for m in models:
            self._fields.pop(m, None)
            self._methods.pop(m, None)
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
