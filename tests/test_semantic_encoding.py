from __future__ import annotations

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_ls.features.semantic import SEMANTIC_LEGEND, resolve_semantic_tokens

VIEW_URI = "file:///tmp/mock_hmx/views/order.xml"
VIEW_XML = """<hmx>
  <record id="view_order" model="baseuiview">
    <field name="model">saleorder</field>
    <field name="arch" type="xml">
      <form>
        <field name="partner" widget="statinfo"/>
        <field name="nosuchfield"/>
        <button name="action_confirm" type="object"/>
      </form>
    </field>
  </record>
</hmx>
"""


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


def _tuples(data):
    return [tuple(data[i:i + 5]) for i in range(0, len(data), 5)]


def test_semantic_stream_is_valid_lsp_delta_encoding():
    result = resolve_semantic_tokens(MockServer({VIEW_URI: VIEW_XML}), VIEW_URI)
    data = result.data
    assert data, "provider produced no tokens for a populated view"
    assert len(data) % 5 == 0, "token stream must be 5-tuples"

    legend_size = len(SEMANTIC_LEGEND.token_types)
    modifier_ceiling = 1 << len(SEMANTIC_LEGEND.token_modifiers)
    line = 0
    char = 0
    for delta_line, delta_char, length, token_type, modifiers in _tuples(data):
        assert delta_line >= 0, "tokens must be emitted in document order"
        assert length > 0
        assert 0 <= token_type < legend_size, (
            f"token type {token_type} outside legend of {legend_size}"
        )
        assert 0 <= modifiers < modifier_ceiling
        if delta_line:
            line += delta_line
            char = delta_char
        else:
            assert delta_char >= 0, "same-line tokens must not move backwards"
            char += delta_char
    assert line > 0


def test_semantic_provider_is_empty_for_unhandled_language():
    uri = "file:///tmp/mock_hmx/static/js/app.js"
    result = resolve_semantic_tokens(MockServer({uri: "const a = 1;\n"}), uri)
    assert result.data == []
