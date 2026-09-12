from __future__ import annotations

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor


def test_xml_cursor_field_and_widget():
    xml = """<record id="view_employee" model="baseuiview">
    <field name="model">hremployee</field>
    <field name="arch" type="xml">
        <form>
            <field name="department" widget="statinfo" />
        </form>
    </field>
</record>"""
    ctx_field = resolve_xml_cursor(xml, line=5, col=26)
    assert ctx_field is not None
    assert ctx_field.kind == "field"
    assert ctx_field.value == "department"
    assert ctx_field.active_model == "hremployee"

    ctx_widget = resolve_xml_cursor(xml, line=5, col=48)
    assert ctx_widget is not None
    assert ctx_widget.kind == "widget"
    assert ctx_widget.value == "statinfo"
    assert ctx_widget.active_model == "hremployee"


def test_xml_cursor_subview_comodel():
    idx = Index()
    idx.entry("accountmove").comodel["line_ids"] = "accountmoveline"
    idx.entry("accountmoveline").declared["amount"] = Loc("line.py", 10, 4)
    resolver = Resolver(idx)

    xml = """<record id="view_invoice" model="baseuiview">
    <field name="model">accountmove</field>
    <field name="arch" type="xml">
        <form>
            <field name="line_ids">
                <tree>
                    <field name="amount" />
                </tree>
            </field>
        </form>
    </field>
</record>"""
    ctx = resolve_xml_cursor(xml, line=7, col=38, resolver=resolver)
    assert ctx is not None
    assert ctx.kind == "field"
    assert ctx.value == "amount"
    assert ctx.active_model == "accountmoveline"


def test_py_cursor_model_and_fk():
    py = """class MyOrder(models.Model):
    class Meta:
        name = "myorder"

    partner_id = models.ForeignKey("partners.respartner", on_delete=models.CASCADE)

    def do_action(self):
        p = self.env["respartner"]
        record = self.env.ref("core_sale.order_1")
"""
    ctx_fk = resolve_py_cursor(py, line=5, col=45)
    assert ctx_fk is not None
    assert ctx_fk.kind == "model"
    assert ctx_fk.value == "respartner"

    ctx_env = resolve_py_cursor(py, line=8, col=26)
    assert ctx_env is not None
    assert ctx_env.kind == "model"
    assert ctx_env.value == "respartner"

    ctx_ref = resolve_py_cursor(py, line=9, col=34)
    assert ctx_ref is not None
    assert ctx_ref.kind == "xmlid"
    assert ctx_ref.value == "core_sale.order_1"


def test_py_cursor_dotted_field():
    py = """class SubOrder(models.Model):
    class Meta:
        name = "suborder"

    partner_name = fields.CharField(related="order_id.partner_id.name")
"""
    ctx_hop0 = resolve_py_cursor(py, line=5, col=48)
    assert ctx_hop0 is not None
    assert ctx_hop0.kind == "dotted_field"
    assert ctx_hop0.hop_index == 0

    ctx_hop1 = resolve_py_cursor(py, line=5, col=57)
    assert ctx_hop1 is not None
    assert ctx_hop1.kind == "dotted_field"
    assert ctx_hop1.hop_index == 1

    ctx_hop2 = resolve_py_cursor(py, line=5, col=68)
    assert ctx_hop2 is not None
    assert ctx_hop2.kind == "dotted_field"
    assert ctx_hop2.hop_index == 2
