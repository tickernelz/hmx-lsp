from __future__ import annotations

import os
from lsprotocol import types

from hmx_core.index import Index, ModelEntry
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_core.webx import ComponentEntry, WebxIndex, WidgetEntry
from hmx_core.xmlids import XmlIdEntry, XmlIdIndex
from hmx_ls.features.completion import resolve_completion
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics
from hmx_ls.features.hover import resolve_hover
from hmx_ls.features.references import resolve_references
from hmx_ls.features.symbols import resolve_document_symbols, resolve_workspace_symbols


class MockWorkspace:
    def __init__(self, docs: dict[str, str]):
        self.docs = docs

    def get_text_document(self, uri: str):
        if uri in self.docs:
            class MockDoc:
                source = self.docs[uri]
            return MockDoc()
        return None


class MockServer:
    def __init__(self, root: str, docs: dict[str, str]):
        self.root = root
        self.index = Index()
        self.resolver = Resolver(self.index)
        self.workspace = MockWorkspace(docs)


def setup_mock_server() -> MockServer:
    root = "/tmp/mock_hmx"
    docs = {}

    server = MockServer(root, docs)

    emp = server.index.entry("hremployee")
    emp.sites.append(Loc("models/hr.py", 15, 0))
    emp.declared["department_id"] = Loc("models/hr.py", 20, 4)
    emp.declared["salary"] = Loc("models/hr.py", 21, 4)
    emp.comodel["department_id"] = "hrdepartment"

    dept = server.index.entry("hrdepartment")
    dept.sites.append(Loc("models/dept.py", 10, 0))
    dept.declared["name"] = Loc("models/dept.py", 12, 4)

    server.index.xmlids.entries["core_hr.view_employee"] = XmlIdEntry(
        xmlid="core_hr.view_employee",
        model="baseuiview",
        name="view.hr.employee",
        loc=Loc("views/hr_views.xml", 5, 0),
    )
    server.index.xmlids.entries["base.group_user"] = XmlIdEntry(
        xmlid="base.group_user",
        model="basegroup",
        name="Internal User",
        loc=Loc("security/groups.xml", 2, 0),
    )

    server.index.webx.widgets["statinfo"] = WidgetEntry(
        name="statinfo",
        component_name="hx-stat-info",
        registry_type="form",
        loc=Loc("static/js/stat.js", 10, 0),
    )
    server.index.webx.components["hx-stat-info"] = ComponentEntry(
        name="hx-stat-info",
        vue_loc=Loc("static/vue/stat.vue", 1, 0),
        js_loc=Loc("static/js/stat.js", 1, 0),
    )

    xml_content = """<record id="view_employee" model="baseuiview">
    <field name="model">hremployee</field>
    <field name="arch" type="xml">
        <form>
            <field name="department_id" widget="statinfo" />
        </form>
    </field>
</record>"""
    xml_uri = "file:///tmp/mock_hmx/views/hr_views.xml"
    docs[xml_uri] = xml_content

    py_content = """class HrEmployee(models.Model):
    class Meta:
        name = "hremployee"

    department_id = models.ForeignKey("hrdepartment", on_delete=models.CASCADE)
    salary = models.FloatField()

    @api.depends("department_id.name", "salary")
    def _compute_bonus(self):
        pass

    @api.onchange("department_id")
    def _onchange_department(self):
        pass

    @api.model
    def bulk_update(self):
        pass
"""
    py_uri = "file:///tmp/mock_hmx/models/hr.py"
    docs[py_uri] = py_content

    return server


def test_definition_xml_field():
    server = setup_mock_server()
    uri = "file:///tmp/mock_hmx/views/hr_views.xml"
    pos = types.Position(line=4, character=26)
    locs = resolve_definition(server, uri, pos)
    assert len(locs) == 1
    assert locs[0].uri.endswith("models/hr.py")
    assert locs[0].range.start.line == 19


def test_definition_xml_widget():
    server = setup_mock_server()
    uri = "file:///tmp/mock_hmx/views/hr_views.xml"
    pos = types.Position(line=4, character=50)
    locs = resolve_definition(server, uri, pos)
    assert len(locs) == 1
    assert locs[0].uri.endswith("static/vue/stat.vue")


def test_definition_py_decorator_depends_hop():
    server = setup_mock_server()
    uri = "file:///tmp/mock_hmx/models/hr.py"
    pos = types.Position(line=7, character=22)
    locs = resolve_definition(server, uri, pos)
    assert len(locs) == 1
    assert locs[0].uri.endswith("models/hr.py")
    assert locs[0].range.start.line == 19

    pos_hop1 = types.Position(line=7, character=33)
    locs_hop1 = resolve_definition(server, uri, pos_hop1)
    assert len(locs_hop1) == 1
    assert locs[0].uri.endswith("models/hr.py")
    assert locs_hop1[0].uri.endswith("models/dept.py")
    assert locs_hop1[0].range.start.line == 11


def test_hover_decorator():
    server = setup_mock_server()
    uri = "file:///tmp/mock_hmx/models/hr.py"
    pos = types.Position(line=15, character=9)
    h = resolve_hover(server, uri, pos)
    assert h is not None
    assert "@api.model" in h.contents.value

    pos_field = types.Position(line=7, character=22)
    h_field = resolve_hover(server, uri, pos_field)
    assert h_field is not None
    assert "department_id" in h_field.contents.value
    assert "hrdepartment" in h_field.contents.value


def test_completion_decorators():
    server = setup_mock_server()
    uri = "file:///tmp/mock_hmx/models/hr.py"
    server.workspace.docs[uri] = """class HrEmployee(models.Model):
    class Meta:
        name = 'hremployee'
    @api."""
    pos = types.Position(line=3, character=9)
    comp = resolve_completion(server, uri, pos)
    labels = [i.label for i in comp.items]
    assert "@api.depends" in labels
    assert "@api.onchange" in labels
    assert "@api.constrains" in labels
    assert "@api.model" in labels


def test_completion_decorator_fields():
    server = setup_mock_server()
    uri = "file:///tmp/mock_hmx/models/hr.py"
    server.workspace.docs[uri] = """class HrEmployee(models.Model):
    class Meta:
        name = 'hremployee'
    @api.onchange('dept')
    def x(): pass"""
    pos = types.Position(line=3, character=20)
    comp = resolve_completion(server, uri, pos)
    labels = [i.label for i in comp.items]
    assert "department_id" in labels
    assert "salary" in labels


def test_diagnostics_decorator_unknown_field():
    server = setup_mock_server()
    bad_py = """class HrEmployee(models.Model):
    class Meta:
        name = "hremployee"

    @api.depends("non_existent_field")
    def _compute_bonus(self):
        pass
"""
    bad_uri = "file:///tmp/mock_hmx/models/bad.py"
    server.workspace.docs[bad_uri] = bad_py
    diags = compute_diagnostics(server, bad_uri)
    assert len(diags) == 1
    assert diags[0].code == "hmx-unknown-field"
    assert "non_existent_field" in diags[0].message


def test_diagnostics_python_unknown_fk_and_env():
    server = setup_mock_server()
    bad_py = """class HrEmployee(models.Model):
    class Meta:
        name = "hremployee"

    bad_fk = models.ForeignKey("non_existent_model", on_delete=models.CASCADE)

    def test_env(self):
        x = self.env["missing_model"]
        y = self.env.ref("missing.xmlid")
"""
    bad_uri = "file:///tmp/mock_hmx/models/bad2.py"
    server.workspace.docs[bad_uri] = bad_py
    diags = compute_diagnostics(server, bad_uri)
    codes = [d.code for d in diags]
    assert "hmx-unknown-model" in codes
    assert "hmx-unknown-xmlid" in codes


def test_diagnostics_xml_unknown_ref_and_group_and_duplicate():
    server = setup_mock_server()
    bad_xml = """<hmx>
    <record id="view_1" model="baseuiview">
        <field name="model">hremployee</field>
        <field name="inherit" ref="missing.view_base" />
        <field name="arch" type="xml">
            <form groups="missing.group_xyz">
                <field name="department_id" />
            </form>
        </field>
    </record>
    <record id="view_1" model="baseuiview">
        <field name="name">Duplicate View</field>
    </record>
</hmx>"""
    bad_uri = "file:///tmp/mock_hmx/views/bad_refs.xml"
    server.workspace.docs[bad_uri] = bad_xml
    diags = compute_diagnostics(server, bad_uri)
    codes = [d.code for d in diags]
    assert "hmx-unknown-xmlid" in codes
    assert "hmx-unknown-group" in codes
    assert "hmx-duplicate-xmlid" in codes


def test_diagnostics_csv_security():
    server = setup_mock_server()
    bad_csv = """id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_emp,access.emp,model_missing_model,base.missing_group,1,1,1,1
"""
    bad_uri = "file:///tmp/mock_hmx/security/base.model.access.csv"
    server.workspace.docs[bad_uri] = bad_csv
    diags = compute_diagnostics(server, bad_uri)
    codes = [d.code for d in diags]
    assert "hmx-unknown-model" in codes
    assert "hmx-unknown-group" in codes


def test_diagnostics_js_call_kw():
    server = setup_mock_server()
    bad_js = """
    useFetch('/hmx_api/web/dataset/call_kw', { model: 'missing_model', method: 'foo' });
    useFetch('/hmx_api/non_existent_endpoint', {});
    """
    bad_uri = "file:///tmp/mock_hmx/static/js/bad.js"
    server.workspace.docs[bad_uri] = bad_js
    diags = compute_diagnostics(server, bad_uri)
    codes = [d.code for d in diags]
    assert "hmx-unknown-model" in codes
    assert "hmx-unknown-route" in codes


def test_symbols_and_workspace():
    server = setup_mock_server()
    uri = "file:///tmp/mock_hmx/views/hr_views.xml"
    doc_syms = resolve_document_symbols(server, uri)
    assert len(doc_syms) == 1
    assert "view_employee" in doc_syms[0].name

    ws_syms = resolve_workspace_symbols(server, "hr")
    ws_names = [s.name for s in ws_syms]
    assert "hremployee" in ws_names or "hrdepartment" in ws_names


def test_inheritance_fields_and_methods():
    server = setup_mock_server()
    parent = server.index.entry("parent_model")
    parent.declared["parent_field"] = Loc("models/parent.py", 5, 4)
    parent.methods["calculate_allowance"] = Loc("models/parent.py", 10, 4)

    child = server.index.entry("child_model")
    child.declared["child_field"] = Loc("models/child.py", 8, 4)
    child.methods["child_action"] = Loc("models/child.py", 15, 4)
    child.edges.add("parent_model")
    server.resolver.invalidate()

    composed_fields = server.resolver.fields("child_model")
    assert "parent_field" in composed_fields
    assert "child_field" in composed_fields

    composed_methods = server.resolver.methods("child_model")
    assert "calculate_allowance" in composed_methods
    assert "child_action" in composed_methods

    js_code = """
    useFetch('/hmx_api/web/dataset/call_kw', { model: 'child_model', method: 'calculate_allowance' });
    useFetch('/hmx_api/web/dataset/call_kw', { model: 'child_model', method: 'non_existent_method' });
    """
    js_uri = "file:///tmp/mock_hmx/static/js/test_inherit.js"
    server.workspace.docs[js_uri] = js_code

    pos = types.Position(line=1, character=84)
    locs = resolve_definition(server, js_uri, pos)
    assert len(locs) == 1
    assert locs[0].uri.endswith("models/parent.py")
    assert locs[0].range.start.line == 9

    diags = compute_diagnostics(server, js_uri)
    codes = [d.code for d in diags]
    messages = [d.message for d in diags]
    assert "hmx-unknown-method" in codes
    assert any("non_existent_method" in m for m in messages)
    assert not any("calculate_allowance" in m for m in messages)
