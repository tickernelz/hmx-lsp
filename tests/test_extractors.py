from __future__ import annotations

from lxml import etree

from hmx_core.locations import Loc
from hmx_core.manifest import owner_of
from hmx_core.pysource import extract
from hmx_core.resolve import Resolver
from hmx_core.routes import normalize_path
from hmx_core.security import normalize_model_id
from hmx_core.webx import extract_js_file, extract_vue_file
from hmx_core.xmlids import extract_xmlids_from_tree, qualify_xmlid
from hmx_core.index import Index, assemble


def test_manifest_owner():
    assert owner_of("hmx/module/basic/core_hr/models/hr.py") == "core_hr"
    assert owner_of("hmx/module/core/fleet/views/fleet.xml") == "fleet"
    assert owner_of("other/path/file.py") is None


def test_pysource_extract():
    code = b"""
from django.db import models

class MyModel(models.Model):
    class Meta:
        name = "mymodel"

    name = models.CharField(max_length=100)
    parent_id = models.ForeignKey("mymodel", related_name="children", on_delete=models.CASCADE)
"""
    decls, factories = extract(code, "test.py", "test_mod")
    assert len(decls) == 1
    decl = decls[0]
    assert decl.model == "mymodel"
    assert len(decl.fields) == 2
    f_map = {f.name: f for f in decl.fields}
    assert "name" in f_map
    assert "parent_id" in f_map
    assert f_map["parent_id"].comodel == "mymodel"
    assert f_map["parent_id"].related_name == "children"


def test_xmlids_extract():
    xml = b"""<hmx>
    <record id="view_test" model="baseuiview">
        <field name="name">Test View</field>
        <field name="model">mymodel</field>
    </record>
    <menuitem id="menu_test" name="Test Menu" action="act_test"/>
</hmx>"""
    tree = etree.fromstring(xml)
    entries = extract_xmlids_from_tree(tree, "test.xml", "my_module")
    assert len(entries) == 2
    e_map = {e.xmlid: e for e in entries}
    assert "my_module.view_test" in e_map
    assert e_map["my_module.view_test"].model == "baseuiview"
    assert "my_module.menu_test" in e_map
    assert e_map["my_module.menu_test"].action == "act_test"


def test_qualify_xmlid():
    assert qualify_xmlid("my_record", "core_hr") == "core_hr.my_record"
    assert qualify_xmlid("base.my_record", "core_hr") == "base.my_record"
    assert qualify_xmlid("", "core_hr") == ""


def test_normalize_model_id():
    assert normalize_model_id("model_hr_employee") == "hremployee"
    assert normalize_model_id("model_core_inventory_stock_move") == "coreinventorystockmove"
    assert normalize_model_id("hremployee") == "hremployee"


def test_normalize_path():
    assert normalize_path("/leads/{lead_id}/") == "/leads/{lead_id}"
    assert normalize_path("leads/list") == "/leads/list"
    assert normalize_path("/") == "/"


def test_resolver_composition():
    idx = Index()
    entry = idx.entry("parent_model")
    entry.declared["title"] = Loc("parent.py", 10, 4)

    child = idx.entry("child_model")
    child.declared["subtitle"] = Loc("child.py", 5, 4)
    child.edges.add("parent_model")

    resolver = Resolver(idx)
    assert resolver.known("child_model")
    fields = resolver.fields("child_model")
    assert "title" in fields
    assert "subtitle" in fields
    assert fields["title"].path == "parent.py"
    assert fields["subtitle"].path == "child.py"

    resolver.invalidate({"child_model"})
    assert "child_model" not in resolver._fields
