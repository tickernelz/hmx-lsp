from __future__ import annotations

from .locations import FRAMEWORK, Loc
from .pysource import ClassDecl

CONTENTTYPE = "contenttype"
EXTERNAL_BASE_FIELDS = {
    "user": ("username", "password", "first_name", "last_name", "email",
             "is_staff", "is_active", "is_superuser", "date_joined",
             "last_login", "groups", "user_permissions"),
}
DJANGO_USER_FIELDS = ("username", "password", "first_name", "last_name", "email",
                      "is_staff", "is_active", "is_superuser", "date_joined",
                      "last_login", "groups", "user_permissions")


def auto_rule_of(decl: ClassDecl, module_active_rule: bool) -> bool:
    if decl.auto_rule is not None:
        return bool(decl.auto_rule)
    concrete = not (decl.abstract or decl.proxy or decl.auto_created)
    return concrete and module_active_rule


def injected(decl: ClassDecl, module_active_rule: bool) -> dict[str, tuple[Loc, str | None]]:
    has_log_access = bool(decl.auto)
    should_add_foreign = decl.alias is None and has_log_access and decl.model != CONTENTTYPE
    out: dict[str, tuple[Loc, str | None]] = {
        "id": (FRAMEWORK, None),
        "display_name": (FRAMEWORK, None),
    }
    if has_log_access:
        if decl.active_name:
            out[decl.active_name] = (FRAMEWORK, None)
        out["created_at"] = (FRAMEWORK, None)
        out["updated_at"] = (FRAMEWORK, None)
        out["celery_task_id"] = (FRAMEWORK, None)
    if should_add_foreign:
        out["created_by"] = (FRAMEWORK, "user")
        out["edited_by"] = (FRAMEWORK, "user")
    if not decl.transient:
        out["logs"] = (FRAMEWORK, None)
    if auto_rule_of(decl, module_active_rule):
        out["company"] = (FRAMEWORK, "basecompany")
        out["branch"] = (FRAMEWORK, "basebranch")
    return out
