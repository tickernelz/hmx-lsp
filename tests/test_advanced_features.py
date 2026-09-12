from __future__ import annotations

import os
from lsprotocol import types

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_core.webx import ComponentEntry, WidgetEntry
from hmx_core.xmlids import XmlIdEntry
from hmx_ls.features.code_actions import resolve_code_actions
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.document_link import resolve_document_links
from hmx_ls.features.rename import prepare_rename, resolve_rename


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


def setup_advanced_mock_server() -> MockServer:
    root = "/tmp/mock_adv"
    docs = {}
    server = MockServer(root, docs)

    emp = server.index.entry("hremployee")
    emp.declared["department_id"] = Loc("models/hr.py", 10, 4)
    emp.declared["salary"] = Loc("models/hr.py", 11, 4)
    server.index.file_models["models/hr.py"] = ["hremployee"]

    server.index.xmlids.entries["core_hr.view_parent"] = XmlIdEntry(
        xmlid="core_hr.view_parent",
        model="baseuiview",
        name="view.parent",
        loc=Loc("views/parent_views.xml", 2, 0),
    )
    server.index.xmlids.by_file["views/parent_views.xml"] = ["core_hr.view_parent"]
    server.index.xmlids.by_file["views/child_views.xml"] = ["core_hr.view_child"]

    parent_xml = """<record id="view_parent" model="baseuiview">
    <field name="model">hremployee</field>
    <field name="arch" type="xml">
        <form>
            <field name="department_id" />
            <field name="salary" />
        </form>
    </field>
</record>"""
    parent_uri = "file:///tmp/mock_adv/views/parent_views.xml"
    docs[parent_uri] = parent_xml

    child_xml = """<record id="view_child" model="baseuiview">
    <field name="model">hremployee</field>
    <field name="inherit" ref="core_hr.view_parent" />
    <field name="arch" type="xml">
        <xpath expr="//field[@name='salary']" position="after">
            <field name="department_id" />
        </xpath>
    </field>
</record>"""
    child_uri = "file:///tmp/mock_adv/views/child_views.xml"
    docs[child_uri] = child_xml

    py_code = """class HrEmployee(models.Model):
    class Meta:
        name = "hremployee"

    department_id = models.ForeignKey("hrdepartment", on_delete=models.CASCADE)
    salary = models.FloatField()

    @api.depends("department_id", "salary")
    def _calc(self): pass
"""
    py_uri = "file:///tmp/mock_adv/models/hr.py"
    docs[py_uri] = py_code

    server.index.webx.widgets["statinfo"] = WidgetEntry("statinfo", "hx-stat-info", "form", Loc("js/stat.js", 1, 0))
    server.index.webx.components["hx-stat-info"] = ComponentEntry("hx-stat-info", js_loc=Loc("js/stat.js", 1, 0))

    return server


def test_xpath_definition_target(tmp_path):
    server = setup_advanced_mock_server()
    server.root = str(tmp_path)

    p_file = tmp_path / "views" / "parent_views.xml"
    p_file.parent.mkdir(parents=True, exist_ok=True)
    p_file.write_text(server.workspace.docs["file:///tmp/mock_adv/views/parent_views.xml"], encoding="utf-8")

    server.index.xmlids.entries["core_hr.view_parent"].loc = Loc(f"views/parent_views.xml", 2, 0)

    child_uri = "file:///tmp/mock_adv/views/child_views.xml"
    pos = types.Position(line=4, character=25)
    locs = resolve_definition(server, child_uri, pos)
    assert len(locs) == 1
    assert "parent_views.xml" in locs[0].uri
    assert locs[0].range.start.line == 5


def test_prepare_and_resolve_rename():
    server = setup_advanced_mock_server()
    py_uri = "file:///tmp/mock_adv/models/hr.py"
    pos = types.Position(line=4, character=6)

    prep = prepare_rename(server, py_uri, pos)
    assert prep is not None
    assert prep.placeholder == "department_id"

    edit = resolve_rename(server, py_uri, pos, "dept_id")
    assert edit is not None
    assert py_uri in edit.changes
    assert any("dept_id" in change.new_text for change in edit.changes[py_uri])

    child_uri = "file:///tmp/mock_adv/views/child_views.xml"
    assert child_uri in edit.changes
    assert any(change.new_text == "dept_id" for change in edit.changes[child_uri])


def test_document_links_resolution():
    server = setup_advanced_mock_server()
    child_uri = "file:///tmp/mock_adv/views/child_views.xml"
    links = resolve_document_links(server, child_uri)
    assert len(links) >= 1
    assert any("parent_views.xml" in link.target for link in links)


def test_code_actions_quickfix():
    server = setup_advanced_mock_server()
    bad_xml = """<record id="v" model="baseuiview">
    <field name="model">hremployee</field>
    <field name="arch" type="xml">
        <form>
            <field name="departmnt_id" widget="stat_info" />
        </form>
    </field>
</record>"""
    uri = "file:///tmp/mock_adv/views/bad.xml"
    server.workspace.docs[uri] = bad_xml

    diag_widget = types.Diagnostic(
        range=types.Range(types.Position(4, 38), types.Position(4, 56)),
        message="Unknown widget 'stat_info'",
        code="hmx-unknown-widget",
    )
    context = types.CodeActionContext(diagnostics=[diag_widget])
    actions = resolve_code_actions(server, uri, diag_widget.range, context)
    assert len(actions) >= 1
    assert any("statinfo" in a.title for a in actions)
