from __future__ import annotations

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_core.xmlids import XmlIdEntry
from hmx_ls.features.diagnostics import compute_diagnostics

URI = 'file:///tmp/mock_hmx/hmx/module/basic/demo/models/order.py'


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


def _server(source: str) -> MockServer:
    server = MockServer({URI: source})
    order = server.index.entry("saleorder")
    order.sites.append(Loc("models/order.py", 1, 0))
    order.declared["partner"] = Loc("models/order.py", 5, 4)
    order.methods["_compute_total"] = Loc("models/order.py", 9, 4)
    line = server.index.entry("saleline")
    line.sites.append(Loc("models/line.py", 1, 0))
    line.declared["label"] = Loc("models/line.py", 4, 4)
    line.methods["_compute_label"] = Loc("models/line.py", 8, 4)
    server.index.xmlids.entries["base.group_user"] = XmlIdEntry(
        xmlid="base.group_user",
        model="basegroup",
        name="Internal User",
        loc=Loc("security/groups.xml", 2, 0),
    )
    return server


def _report(source: str) -> list[tuple[int, str]]:
    return [(d.range.start.line, str(d.code)) for d in compute_diagnostics(_server(source), URI)]


def _messages(source: str) -> list[str]:
    return [d.message for d in compute_diagnostics(_server(source), URI)]


MULTI = 'from hmx import api, models\n\n\nclass SaleOrder(models.Model):\n    class Meta:\n        name = "saleorder"\n\n    partner = models.ForeignKey("nosuchmodel")\n    total = models.CharField(compute="_compute_missing")\n\n    @api.depends("nosuchfield")\n    def _compute_total(self):\n        self.env["nosuchmodel"].search([])\n        self.env.ref("demo.nosuch_record")\n'

TWO_CLASSES = 'from hmx import api, models\n\n\nclass SaleOrder(models.Model):\n    class Meta:\n        name = "saleorder"\n\n    @api.depends("nosuchfield")\n    def _compute_total(self):\n        self.env.ref("demo.nosuch_record")\n\n\nclass SaleLine(models.Model):\n    class Meta:\n        name = "saleline"\n\n    order = models.ForeignKey("nosuchmodel")\n    label = models.CharField(compute="_compute_missing")\n\n    def _compute_label(self):\n        self.env["nosuchmodel"].search([])\n'

CLEAN = 'from hmx import api, models\n\n\nclass SaleOrder(models.Model):\n    class Meta:\n        name = "saleorder"\n\n    partner = models.ForeignKey("saleline")\n    total = models.CharField(compute="_compute_total")\n\n    @api.depends("partner")\n    def _compute_total(self):\n        self.env["saleline"].search([])\n        self.env.ref("base.group_user")\n'

DEPENDS = 'from hmx import api, models\n\n\nclass SaleOrder(models.Model):\n    class Meta:\n        name = "saleorder"\n\n    @api.depends("nosuchfield")\n    def _compute_total(self):\n        pass\n'

RELATIONAL = 'from hmx import models\n\n\nclass SaleOrder(models.Model):\n    class Meta:\n        name = "saleorder"\n\n    partner = models.ForeignKey("nosuchmodel")\n'

COMPUTE = 'from hmx import models\n\n\nclass SaleOrder(models.Model):\n    class Meta:\n        name = "saleorder"\n\n    total = models.CharField(compute="_compute_missing")\n'

ENV_MODEL = 'def handler(self):\n    return self.env["nosuchmodel"].search([])\n'

ENV_REF = 'def handler(self):\n    return self.env.ref("demo.nosuch_record")\n'


def test_api_depends_flags_unknown_field():
    assert _report(DEPENDS) == [(7, "hmx-unknown-field")]
    assert "Unknown field 'nosuchfield' on model 'saleorder' in @api.depends" in _messages(DEPENDS)


def test_relational_field_flags_unknown_target_model():
    assert _report(RELATIONAL) == [(7, "hmx-unknown-model")]
    assert "Unknown target model 'nosuchmodel' in ForeignKey" in _messages(RELATIONAL)


def test_compute_kwarg_flags_method_missing_on_model():
    assert _report(COMPUTE) == [(7, "hmx-unknown-method")]
    assert [m for m in _messages(COMPUTE) if "_compute_missing" in m and "saleorder" in m]


def test_env_subscript_flags_unknown_model():
    assert _report(ENV_MODEL) == [(1, "hmx-unknown-model")]
    assert "Unknown model 'nosuchmodel' in env[...]" in _messages(ENV_MODEL)


def test_env_ref_flags_unknown_xmlid():
    assert _report(ENV_REF) == [(1, "hmx-unknown-xmlid")]
    assert "Unknown XMLID 'demo.nosuch_record' in env.ref(...)" in _messages(ENV_REF)


def test_bare_env_ref_is_still_inspected():
    assert _report('env.ref("demo.nosuch_record")\n') == [(0, "hmx-unknown-xmlid")]


def test_multi_defect_file_keeps_class_diagnostics_before_env_diagnostics():
    assert _report(MULTI) == [
        (7, "hmx-unknown-model"),
        (8, "hmx-unknown-method"),
        (10, "hmx-unknown-field"),
        (13, "hmx-unknown-xmlid"),
        (12, "hmx-unknown-model"),
    ]


def test_env_diagnostics_never_interleave_between_two_classes():
    assert _report(TWO_CLASSES) == [
        (7, "hmx-unknown-field"),
        (16, "hmx-unknown-model"),
        (17, "hmx-unknown-method"),
        (9, "hmx-unknown-xmlid"),
        (20, "hmx-unknown-model"),
    ]


def test_resolvable_references_produce_nothing():
    assert _report(CLEAN) == []


def test_unparsable_python_is_skipped():
    assert _report("class Broken(:\n") == []
