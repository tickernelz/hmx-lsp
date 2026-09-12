from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .locations import Loc
from .manifest import owner_of

BUILTIN_WIDGETS = {
    "ace", "activity_management", "approval_config", "approval_history", "approval_levels", "approval_levels_v2",
    "auto_approval_timeout", "badge", "barcode_scanner", "binary", "boolean", "boolean_toggle", "boolean_toggle_status",
    "char", "checkbox", "color_picker", "comben_detail", "cost_center_analytic_distribution", "dashboard_preview",
    "dashboard_preview_v2", "dashboard_standalone_preview", "date", "datetime", "dimension_float", "document_pdf_signer_embed",
    "download", "email", "expandable_detail", "external-link", "float", "handle", "heading", "html", "id_card_preview",
    "image", "integer", "json_params", "leave_color_badge", "leave_employee_accordion", "leave_kpi_card", "leave_kpi_row",
    "leave_lt_line_table", "leave_mv_kpi_strip", "leave_progress_bar", "leave_record_card", "leave_source_pill", "m2m_avatar",
    "m2m_team_performance", "m2m_user_count", "manufacture_product_replace", "manufacture_qty_input",
    "manufacture_review_confirm", "many2many", "many2many-v2", "many2many_tags", "many2many_v2", "many2one",
    "many2one_avatar", "marketplace_json_viewer", "monetary", "multiple_reviewer_config", "nine_box_matrix_preview",
    "notification_settings", "one2many", "one2many-v2", "one2many_v2", "optional_perimeter", "org-widget", "org_widget",
    "payroll_run_detail", "payslip_detail", "pdf-viewer", "pdf_viewer", "percentage", "percentage_pie", "phone",
    "phoneintl", "pp_assign_manager", "pp_basic_info", "pp_company_goals", "pp_employees", "pp_publish_employees",
    "pp_setup_progress", "pp_team_goals", "primary_perimeter", "profile_card", "progress-bar", "progress_bar",
    "radio", "radiowidget", "relational-v2", "relational_pricelist_config", "relational_v2", "se_exchange_type",
    "se_goals_references", "se_header_info", "se_my_evaluation", "se_schedule_preview", "selection",
    "sql_editor", "statinfo", "statusbar", "string", "subgoal_toggle", "summary", "te_header_info",
    "te_team_evaluation", "team_member_sales", "text", "textarea", "theme_picker", "trigger_conditions",
    "uppercase", "url", "vision_report_lines"
}

RE_VUE_COMPONENT = re.compile(r"VueComponent\.push\(\s*\{\s*name:\s*['\"]([^'\"]+)['\"]")
RE_VUE_TEMPLATE = re.compile(r"<template\s+name=['\"]([^'\"]+)['\"]")
RE_FIELD_REG = re.compile(
    r"FieldRegistry\.register\(\s*['\"]([^'\"]+)['\"]\s*,\s*"
    r"(?:['\"]([^'\"]+)['\"]|([A-Za-z_$][A-Za-z0-9_$]*))"
)
RE_LIST_FIELD_REG = re.compile(
    r"ListFieldRegistry\.register\(\s*['\"]([^'\"]+)['\"]\s*,\s*"
    r"(?:['\"]([^'\"]+)['\"]|([A-Za-z_$][A-Za-z0-9_$]*))"
)
RE_WIDGET_MAP = re.compile(
    r"FieldUtilsV2\.widgetMap\['([^']+)'\]\s*=\s*'([^']+)'|"
    r'FieldUtilsV2\.widgetMap\["([^"]+)"\]\s*=\s*"([^"]+)"'
)
RE_VUE_COMPONENT_IDENT = re.compile(
    r"VueComponent\.push\(\s*\{\s*name:\s*([A-Za-z_$][\w$]*)\s*[,}]"
)
RE_JS_CONST_STR = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*['\"]([^'\"\n]+)['\"]"
)
RE_VUE_TEMPLATE_KEY = re.compile(r"VueTemplate\[\s*['\"]([^'\"]+)['\"]\s*\]")
RE_VUE_TEMPLATE_IDENT = re.compile(r"VueTemplate\[\s*([A-Za-z_$][\w$]*)\s*\]")
RE_DEFINE_STORE = re.compile(r"defineStore\(\s*['\"]([^'\"]+)['\"]")
RE_REGISTER_ACTION = re.compile(r"registerAction\(\s*['\"]([^'\"]+)['\"]")
RE_REGISTER_ACTION_IDENT = re.compile(r"registerAction\(\s*([A-Za-z_$][\w$]*)\s*[,)]")
RE_APP_COMPONENT = re.compile(r"app\.component\(\s*['\"]([^'\"]+)['\"]")
RE_COMPONENT_EXT = re.compile(r"useComponentExtension\(\s*['\"]([^'\"]+)['\"]")
RE_COMPONENT_EXT_IDENT = re.compile(r"useComponentExtension\(\s*([A-Za-z_$][\w$]*)\s*[,)]")
RE_COMPONENT_NAME_SHAPE = re.compile(r"^[A-Za-z][\w]*-[\w-]+$")


@dataclass
class WidgetEntry:
    name: str
    component_name: str
    registry_type: str
    loc: Loc


@dataclass
class ComponentEntry:
    name: str
    js_loc: Loc | None = None
    vue_loc: Loc | None = None


@dataclass
class StoreEntry:
    name: str
    loc: Loc


@dataclass
class WebxIndex:
    widgets: dict[str, WidgetEntry] = field(default_factory=dict)
    components: dict[str, ComponentEntry] = field(default_factory=dict)
    by_file: dict[str, list[str]] = field(default_factory=dict)
    templates: dict[str, Loc] = field(default_factory=dict)
    stores: dict[str, StoreEntry] = field(default_factory=dict)
    actions: dict[str, Loc] = field(default_factory=dict)
    extensions: dict[str, list[Loc]] = field(default_factory=dict)

    def resolve_widget(self, name: str) -> tuple[WidgetEntry | None, ComponentEntry | None]:
        w = self.widgets.get(name)
        if w is None:
            c = self.components.get(name) or self.components.get(f"hx-{name}")
            return None, c
        return w, self.components.get(w.component_name)

    def known_widget(self, name: str) -> bool:
        low = name.lower()
        if low in BUILTIN_WIDGETS or name in BUILTIN_WIDGETS or name in self.widgets:
            return True
        if name in self.components or f"hx-{name}" in self.components:
            return True
        return False

    def known_component(self, name: str) -> bool:
        if not name:
            return False
        if name in self.components or name in self.templates:
            return True
        prefixed = f"hx-{name}"
        return prefixed in self.components or prefixed in self.templates

    def known_store(self, name: str) -> bool:
        return bool(name) and name in self.stores


def extract_js_file(path: str, rel_path: str) -> tuple[list[WidgetEntry], list[tuple[str, Loc]]]:
    widgets: list[WidgetEntry] = []
    comps: list[tuple[str, Loc]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return widgets, comps

    consts = _string_consts(content)

    for m in RE_FIELD_REG.finditer(content):
        line = content[:m.start()].count("\n") + 1
        component = m.group(2) or consts.get(m.group(3) or "", "")
        widgets.append(WidgetEntry(m.group(1), component, "form", Loc(rel_path, line, 0)))

    for m in RE_LIST_FIELD_REG.finditer(content):
        line = content[:m.start()].count("\n") + 1
        component = m.group(2) or consts.get(m.group(3) or "", "")
        widgets.append(WidgetEntry(m.group(1), component, "list", Loc(rel_path, line, 0)))

    for m in RE_WIDGET_MAP.finditer(content):
        w_name = m.group(1) or m.group(3)
        c_name = m.group(2) or m.group(4)
        line = content[:m.start()].count("\n") + 1
        widgets.append(WidgetEntry(w_name, c_name, "relational_v2", Loc(rel_path, line, 0)))

    for m in RE_VUE_COMPONENT.finditer(content):
        line = content[:m.start()].count("\n") + 1
        comps.append((m.group(1), Loc(rel_path, line, 0)))

    consts: dict[str, str] | None = None
    for m in RE_VUE_COMPONENT_IDENT.finditer(content):
        if consts is None:
            consts = _string_consts(content)
        value = consts.get(m.group(1))
        if value is None or not RE_COMPONENT_NAME_SHAPE.match(value):
            continue
        line = content[:m.start()].count("\n") + 1
        comps.append((value, Loc(rel_path, line, 0)))

    return widgets, comps


def _string_consts(content: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in RE_JS_CONST_STR.finditer(content):
        out.setdefault(m.group(1), m.group(2))
    return out


def _literal_and_ident(content: str, rel_path: str, literal: re.Pattern[str],
                       ident: re.Pattern[str] | None,
                       consts: dict[str, str]) -> list[tuple[str, Loc]]:
    found: list[tuple[str, Loc]] = []
    for m in literal.finditer(content):
        line = content[:m.start()].count("\n") + 1
        found.append((m.group(1), Loc(rel_path, line, 0)))
    if ident is None:
        return found
    for m in ident.finditer(content):
        value = consts.get(m.group(1))
        if value is None:
            continue
        line = content[:m.start()].count("\n") + 1
        found.append((value, Loc(rel_path, line, 0)))
    return found


def extract_js_extras(path: str, rel_path: str) -> dict[str, list[tuple[str, Loc]]]:
    empty: dict[str, list[tuple[str, Loc]]] = {
        "templates": [], "stores": [], "actions": [], "extensions": [],
    }
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return empty

    consts = _string_consts(content)
    templates = _literal_and_ident(content, rel_path, RE_VUE_TEMPLATE_KEY, RE_VUE_TEMPLATE_IDENT, consts)
    stores = _literal_and_ident(content, rel_path, RE_DEFINE_STORE, None, consts)
    actions = _literal_and_ident(content, rel_path, RE_REGISTER_ACTION, RE_REGISTER_ACTION_IDENT, consts)
    actions += _literal_and_ident(content, rel_path, RE_APP_COMPONENT, None, consts)
    extensions = _literal_and_ident(content, rel_path, RE_COMPONENT_EXT, RE_COMPONENT_EXT_IDENT, consts)
    return {
        "templates": templates,
        "stores": stores,
        "actions": actions,
        "extensions": extensions,
    }


def extract_vue_file(path: str, rel_path: str) -> list[tuple[str, Loc]]:
    templates: list[tuple[str, Loc]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return templates

    for m in RE_VUE_TEMPLATE.finditer(content):
        line = content[:m.start()].count("\n") + 1
        templates.append((m.group(1), Loc(rel_path, line, 0)))

    return templates


def scan_webx(root: str) -> WebxIndex:
    idx = WebxIndex()
    module_dir = os.path.join(root, "hmx", "module")
    if not os.path.isdir(module_dir):
        return idx

    for dirpath, _, filenames in os.walk(module_dir):
        if any(s in dirpath for s in (".git", "node_modules", "__pycache__")):
            continue
        for f in filenames:
            path = os.path.join(dirpath, f)
            rel = os.path.relpath(path, root)
            if f.endswith(".js"):
                w_list, c_list = extract_js_file(path, rel)
                file_keys: list[str] = []
                for w in w_list:
                    idx.widgets[w.name] = w
                    file_keys.append(f"w:{w.name}")
                for c_name, loc in c_list:
                    comp = idx.components.setdefault(c_name, ComponentEntry(name=c_name))
                    comp.js_loc = loc
                    file_keys.append(f"c:{c_name}")
                if file_keys:
                    idx.by_file[rel] = file_keys
                _absorb_extras(idx, extract_js_extras(path, rel))
            elif f.endswith(".vue"):
                t_list = extract_vue_file(path, rel)
                vue_keys: list[str] = []
                for t_name, loc in t_list:
                    comp = idx.components.setdefault(t_name, ComponentEntry(name=t_name))
                    comp.vue_loc = loc
                    vue_keys.append(f"c:{t_name}")
                if vue_keys:
                    idx.by_file[rel] = vue_keys
                _absorb_extras(idx, extract_js_extras(path, rel))

    return idx


def _absorb_extras(idx: WebxIndex, extras: dict[str, list[tuple[str, Loc]]]) -> None:
    for name, loc in extras["templates"]:
        idx.templates.setdefault(name, loc)
    for name, loc in extras["stores"]:
        idx.stores.setdefault(name, StoreEntry(name=name, loc=loc))
    for name, loc in extras["actions"]:
        idx.actions.setdefault(name, loc)
    for name, loc in extras["extensions"]:
        idx.extensions.setdefault(name, []).append(loc)
