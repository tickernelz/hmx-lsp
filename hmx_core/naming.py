from __future__ import annotations

from typing import Protocol

DOMAIN_KEYWORDS = frozenset({
    "parent", "context", "uid", "user", "company", "active_id", "active_ids",
    "active_model", "today", "now", "datetime", "date", "timedelta", "relativedelta",
    "current_date", "allowed_company_ids", "id", "self",
})
BUILTIN_MODELS = frozenset({"user", "group", "contenttype", "permission", "session"})


class ModelLookup(Protocol):
    def known(self, model: str) -> bool: ...


def model_candidates(raw: str) -> list[str]:
    if not raw:
        return []
    token = raw.strip().split(".")[-1]
    if token.startswith("model_"):
        token = token[6:]
    lowered = token.lower()
    candidates = [lowered]
    collapsed = lowered.replace("_", "")
    if collapsed and collapsed != lowered:
        candidates.append(collapsed)
    dotted = raw.strip().lower().replace(".", "")
    if dotted and dotted not in candidates:
        candidates.append(dotted)
    return candidates


def resolve_model(lookup: ModelLookup, raw: str) -> str | None:
    for candidate in model_candidates(raw):
        if lookup.known(candidate):
            return candidate
    return None


def is_known_model(lookup: ModelLookup, raw: str) -> bool:
    if resolve_model(lookup, raw) is not None:
        return True
    return any(candidate in BUILTIN_MODELS for candidate in model_candidates(raw))


def is_domain_keyword(name: str) -> bool:
    return name.split(".")[0] in DOMAIN_KEYWORDS
