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
    r"FieldRegistry\.register\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]"
)
RE_LIST_FIELD_REG = re.compile(
    r"ListFieldRegistry\.register\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]"
)
RE_WIDGET_MAP = re.compile(
    r"FieldUtilsV2\.widgetMap\['([^']+)'\]\s*=\s*'([^']+)'|"
    r'FieldUtilsV2\.widgetMap\["([^"]+)"\]\s*=\s*"([^"]+)"'
)


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
class WebxIndex:
    widgets: dict[str, WidgetEntry] = field(default_factory=dict)
    components: dict[str, ComponentEntry] = field(default_factory=dict)
    by_file: dict[str, list[str]] = field(default_factory=dict)

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


def extract_js_file(path: str, rel_path: str) -> tuple[list[WidgetEntry], list[tuple[str, Loc]]]:
    widgets: list[WidgetEntry] = []
    comps: list[tuple[str, Loc]] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError:
        return widgets, comps

    for m in RE_FIELD_REG.finditer(content):
        line = content[:m.start()].count("\n") + 1
        widgets.append(WidgetEntry(m.group(1), m.group(2), "form", Loc(rel_path, line, 0)))

    for m in RE_LIST_FIELD_REG.finditer(content):
        line = content[:m.start()].count("\n") + 1
        widgets.append(WidgetEntry(m.group(1), m.group(2), "list", Loc(rel_path, line, 0)))

    for m in RE_WIDGET_MAP.finditer(content):
        w_name = m.group(1) or m.group(3)
        c_name = m.group(2) or m.group(4)
        line = content[:m.start()].count("\n") + 1
        widgets.append(WidgetEntry(w_name, c_name, "relational_v2", Loc(rel_path, line, 0)))

    for m in RE_VUE_COMPONENT.finditer(content):
        line = content[:m.start()].count("\n") + 1
        comps.append((m.group(1), Loc(rel_path, line, 0)))

    return widgets, comps


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
            elif f.endswith(".vue"):
                t_list = extract_vue_file(path, rel)
                vue_keys: list[str] = []
                for t_name, loc in t_list:
                    comp = idx.components.setdefault(t_name, ComponentEntry(name=t_name))
                    comp.vue_loc = loc
                    vue_keys.append(f"c:{t_name}")
                if vue_keys:
                    idx.by_file[rel] = vue_keys

    return idx
