from __future__ import annotations

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_ls.features.diagnostics import compute_diagnostics

URI = "file:///tmp/mock_hmx/views/order.xml"


class MockWorkspace:
    def __init__(self, docs):
        self.docs = docs

    def get_text_document(self, uri):
        if uri not in self.docs:
            return None

        class MockDoc:
            source = self.docs[uri]

        return MockDoc()


class MockServer:
    def __init__(self, docs):
        self.root = "/tmp/mock_hmx"
        self.index = Index()
        self.resolver = Resolver(self.index)
        self.workspace = MockWorkspace(docs)
        order = self.index.entry("saleorder")
        order.sites.append(Loc("models/order.py", 1, 0))
        order.declared["partner"] = Loc("models/order.py", 5, 4)
        order.declared["state"] = Loc("models/order.py", 6, 4)
        order.comodel["partner"] = "basepartner"
        partner = self.index.entry("basepartner")
        partner.sites.append(Loc("models/partner.py", 1, 0))
        partner.declared["is_company"] = Loc("models/partner.py", 3, 4)
        partner.declared["country"] = Loc("models/partner.py", 4, 4)


def _view(body: str) -> str:
    return (
        '<hmx><record id="v" model="baseuiview">'
        '<field name="model">saleorder</field>'
        '<field name="arch" type="xml"><form>'
        f"{body}"
        "</form></field></record></hmx>"
    )


def _messages(body: str) -> list[str]:
    xml = _view(body)
    return [d.message for d in compute_diagnostics(MockServer({URI: xml}), URI)]


def test_domain_leaves_resolve_against_the_comodel():
    got = _messages("<field name=\"partner\" domain=\"[('is_company','=',True)]\"/>")
    assert got == []


def test_domain_leaf_absent_from_the_comodel_is_reported_against_the_comodel():
    got = _messages("<field name=\"partner\" domain=\"[('nosuchfield','=',1)]\"/>")
    assert len(got) == 1
    assert "nosuchfield" in got[0]
    assert "basepartner" in got[0]
    assert "saleorder" not in got[0]


def test_a_parent_model_field_in_a_domain_is_not_silently_accepted():
    got = _messages("<field name=\"partner\" domain=\"[('state','=',1)]\"/>")
    assert len(got) == 1
    assert "'state'" in got[0]
    assert "basepartner" in got[0]


def test_default_context_key_resolves_against_the_comodel():
    clean = _messages(
        '<field name="partner" context="{\'default_country\': 1}"/>')
    assert clean == []
    bad = _messages(
        '<field name="partner" context="{\'default_nosuch\': 1}"/>')
    assert len(bad) == 1
    assert "basepartner" in bad[0]


def test_modifier_attributes_still_resolve_against_the_current_model():
    assert _messages('<field name="partner" invisible="state"/>') == []
    bad = _messages('<field name="partner" invisible="nosuchfield"/>')
    assert len(bad) == 1
    assert "saleorder" in bad[0]


def test_field_name_check_is_unaffected_by_the_scope_change():
    got = _messages('<field name="ghostfield"/>')
    assert len(got) == 1
    assert "saleorder" in got[0]


def test_domain_on_a_non_relational_field_is_not_checked_against_the_parent():
    got = _messages("<field name=\"state\" domain=\"[('anything','=',1)]\"/>")
    assert got == []


def test_domain_outside_a_field_element_still_uses_the_view_model():
    bad = _messages("<list domain=\"[('nosuchfield','=',1)]\"/>")
    assert len(bad) == 1
    assert "saleorder" in bad[0]
