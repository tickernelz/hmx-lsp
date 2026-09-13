from __future__ import annotations

import pytest
from lsprotocol import types

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.hover import resolve_hover

URI = "file:///tmp/mock_hmx/models/purchase.py"

HEADER = '''from hmx import api, models


class PurchaseOrder(models.Model):
    class Meta:
        name = "purchaseorder"

    status = models.CharField()
    expected_date = models.DateTimeField()
    partner = models.ForeignKey("basepartner")

    def _compute(self):
'''


class MockWorkspace:
    def __init__(self, docs):
        self.docs = docs

    def get_text_document(self, uri):
        if uri not in self.docs:
            return None

        class Doc:
            source = self.docs[uri]

        return Doc()


class MockServer:
    def __init__(self, docs):
        self.root = "/tmp/mock_hmx"
        self.index = Index()
        self.resolver = Resolver(self.index)
        self.workspace = MockWorkspace(docs)
        order = self.index.entry("purchaseorder")
        order.sites.append(Loc("models/purchase.py", 4, 0))
        order.declared["status"] = Loc("models/purchase.py", 8, 4)
        order.declared["expected_date"] = Loc("models/purchase.py", 9, 4)
        order.declared["partner"] = Loc("models/purchase.py", 10, 4)
        order.comodel["partner"] = "basepartner"
        partner = self.index.entry("basepartner")
        partner.sites.append(Loc("models/partner.py", 1, 0))
        partner.declared["country"] = Loc("models/partner.py", 3, 4)


def _probe(body: str, anchor: str, attr: str):
    source = HEADER + body
    lines = source.splitlines()
    index = next(i for i, text in enumerate(lines) if anchor in text)
    col = lines[index].index(anchor) + len(anchor)
    server = MockServer({URI: source})
    ctx = resolve_py_cursor(source, index + 1, col, server.resolver)
    position = types.Position(line=index, character=col)
    return ctx, resolve_hover(server, URI, position), resolve_definition(server, URI, position)


@pytest.mark.parametrize("body,anchor", [
    ("        value = self.status\n", "self."),
    ("        for order in self:\n            value = order.status\n", "order."),
    ("        for order in self.filtered(lambda r: r.status):\n"
     "            value = order.status\n", "order."),
    ("        for order in self.search([]):\n            value = order.status\n", "order."),
    ("        rec = self.browse(1)\n        value = rec.status\n", "rec."),
    ("        rec = self.env[\"purchaseorder\"]\n        value = rec.status\n", "rec."),
])
def test_attribute_resolves_through_common_bindings(body, anchor):
    ctx, hover, definition = _probe(body, anchor, "status")
    assert ctx is not None and ctx.kind == "field"
    assert ctx.active_model == "purchaseorder"
    assert ctx.value == "status"
    assert hover is not None
    assert len(definition) == 1


def test_lambda_parameter_resolves_to_the_same_model():
    body = "        hit = self.filtered(lambda record: record.status)\n"
    ctx, hover, definition = _probe(body, "record.", "status")
    assert ctx is not None and ctx.active_model == "purchaseorder"
    assert hover is not None and len(definition) == 1


def test_relational_hop_switches_to_the_comodel():
    body = "        for order in self:\n            value = order.partner.country\n"
    ctx, hover, definition = _probe(body, "partner.", "country")
    assert ctx is not None and ctx.kind == "field"
    assert ctx.active_model == "basepartner"
    assert ctx.value == "country"
    assert len(definition) == 1


def test_unknown_attribute_resolves_to_nothing():
    body = "        for order in self:\n            value = order.nosuchfield\n"
    ctx, hover, definition = _probe(body, "order.", "nosuchfield")
    assert ctx is not None and ctx.active_model == "purchaseorder"
    assert hover is None
    assert definition == []


def test_framework_attributes_are_not_claimed_as_fields():
    for attr in ("pk", "objects", "STATUS_CHOICES", "_meta"):
        body = f"        for order in self:\n            value = order.{attr}\n"
        ctx, _, _ = _probe(body, "order.", attr)
        assert ctx is None or ctx.kind != "field", attr


def test_an_unrelated_local_is_not_treated_as_a_record():
    body = "        other = timezone.now()\n        value = other.status\n"
    ctx, _, definition = _probe(body, "other.", "status")
    assert ctx is None or ctx.kind != "field"
    assert definition == []


def test_the_cursor_on_the_base_is_not_treated_as_a_field():
    source = HEADER + "        for order in self:\n            value = order.status\n"
    lines = source.splitlines()
    index = next(i for i, text in enumerate(lines) if "value = order.status" in text)
    col = lines[index].index("order.") + 1
    server = MockServer({URI: source})
    ctx = resolve_py_cursor(source, index + 1, col, server.resolver)
    assert ctx is None or ctx.value != "status"
