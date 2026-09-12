from __future__ import annotations

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.naming import is_domain_keyword, is_known_model, model_candidates, resolve_model
from hmx_core.resolve import Resolver
from hmx_core.webx import scan_webx
from hmx_core.xmlids import XmlIdEntry
from hmx_ls.features.diagnostics import compute_diagnostics


class MockWorkspace:
    def __init__(self, docs: dict[str, str]):
        self.docs = docs

    def get_text_document(self, uri: str):
        if uri not in self.docs:
            return None

        class MockDoc:
            source = self.docs[uri]

        return MockDoc()


class MockServer:
    def __init__(self, docs: dict[str, str]):
        self.root = "/tmp/mock_hmx"
        self.index = Index()
        self.resolver = Resolver(self.index)
        self.workspace = MockWorkspace(docs)


class FakeLookup:
    def __init__(self, names):
        self._names = set(names)

    def known(self, model: str) -> bool:
        return model in self._names


def _server_with_order(docs: dict[str, str]) -> MockServer:
    server = MockServer(docs)
    order = server.index.entry("saleorder")
    order.sites.append(Loc("models/order.py", 1, 0))
    order.declared["partner"] = Loc("models/order.py", 5, 4)
    order.comodel["partner"] = "basepartner"
    partner = server.index.entry("basepartner")
    partner.sites.append(Loc("models/partner.py", 1, 0))
    partner.declared["name"] = Loc("models/partner.py", 3, 4)
    server.index.xmlids.entries["base.group_user"] = XmlIdEntry(
        xmlid="base.group_user",
        model="basegroup",
        name="Internal User",
        loc=Loc("security/groups.xml", 2, 0),
    )
    return server


def test_synthetic_model_xmlid_strips_module_and_prefix():
    lookup = FakeLookup({"manuf_order"})
    assert resolve_model(lookup, "core_manuf.model_manuf_order") == "manuf_order"
    assert resolve_model(lookup, "model_manuf_order") == "manuf_order"
    assert resolve_model(lookup, "manuf_order") == "manuf_order"


def test_underscore_collapsed_alias_resolves():
    assert resolve_model(FakeLookup({"hremployee"}), "hr_employee") == "hremployee"
    assert resolve_model(FakeLookup({"basebranch"}), "base.base_branch") == "basebranch"


def test_unknown_model_stays_unresolved():
    assert resolve_model(FakeLookup({"hremployee"}), "nosuchmodel") is None
    assert not is_known_model(FakeLookup(set()), "nosuchmodel")


def test_django_builtin_models_known_without_index():
    assert is_known_model(FakeLookup(set()), "auth.user")
    assert is_known_model(FakeLookup(set()), "contenttypes.contenttype")


def test_parent_is_a_domain_keyword():
    assert is_domain_keyword("parent")
    assert is_domain_keyword("parent.company")
    assert is_domain_keyword("active_id")
    assert not is_domain_keyword("partner")


def test_model_candidates_put_most_specific_first():
    assert model_candidates("core_hr.model_hr_employee")[0] == "hr_employee"


def test_registry_register_accepts_identifier_component(tmp_path):
    js = tmp_path / "hmx" / "module" / "basic" / "demo" / "static" / "js"
    js.mkdir(parents=True)
    (js / "sign.js").write_text(
        "const componentName = 'SignField';\n"
        "FieldRegistry.register('sign', componentName);\n"
        "ListFieldRegistry.register('sign_list', componentName);\n"
        "FieldRegistry.register('plain', 'PlainField');\n"
    )
    webx = scan_webx(str(tmp_path))
    assert webx.known_widget("sign")
    assert webx.known_widget("sign_list")
    assert webx.known_widget("plain")
    assert webx.widgets["sign"].component_name == "SignField"
    assert not webx.known_widget("neverregistered")


def test_acl_model_column_accepts_synthetic_xmlid():
    uri = "file:///tmp/mock_hmx/security/ir.model.access.csv"
    csv = (
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "access_a,a,demo.model_saleorder,base.group_user,1,1,1,1\n"
        "access_b,b,demo.model_nosuchmodel,base.group_user,1,1,1,1\n"
    )
    server = _server_with_order({uri: csv})
    found = [(d.code, d.range.start.line) for d in compute_diagnostics(server, uri)]
    assert ("hmx-unknown-model", 2) in found
    assert not [entry for entry in found if entry[1] == 1]


def test_domain_parent_reference_is_not_flagged():
    uri = "file:///tmp/mock_hmx/views/order.xml"
    xml = (
        '<hmx><record id="v" model="baseuiview">'
        '<field name="model">saleorder</field>'
        '<field name="arch" type="xml"><form>'
        "<field name=\"partner\" domain=\"[('id','=',parent.partner)]\"/>"
        "<field name=\"partner\" domain=\"[('nosuchfield','=',1)]\"/>"
        "</form></field></record></hmx>"
    )
    server = _server_with_order({uri: xml})
    messages = [d.message for d in compute_diagnostics(server, uri)]
    assert not [m for m in messages if "'parent'" in m]
    assert [m for m in messages if "nosuchfield" in m]


def test_subview_switches_model_context():
    uri = "file:///tmp/mock_hmx/views/nested.xml"
    xml = (
        '<hmx><record id="v" model="baseuiview">'
        '<field name="model">saleorder</field>'
        '<field name="arch" type="xml"><form>'
        '<field name="partner"><list>'
        '<field name="name"/>'
        '<field name="nosuchpartnerfield"/>'
        "</list></field>"
        "</form></field></record></hmx>"
    )
    server = _server_with_order({uri: xml})
    messages = [d.message for d in compute_diagnostics(server, uri)]
    assert not [m for m in messages if "'name'" in m]
    assert [m for m in messages if "nosuchpartnerfield" in m and "basepartner" in m]
