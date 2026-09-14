from __future__ import annotations

from lsprotocol import types

from hmx_core.index import Index, ModelEntry
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_core.xmlids import XmlIdEntry
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor
from hmx_ls.features.completion import resolve_completion
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics
from hmx_ls.features.hover import resolve_hover
from hmx_ls.features.references import resolve_references

MODEL_URI = "file:///tmp/mock_hmx/data/workflow.xml"


class Workspace:
    def __init__(self, docs):
        self.docs = docs

    def get_text_document(self, uri):
        if uri not in self.docs:
            return None

        class Document:
            source = self.docs[uri]

        return Document()


class Server:
    def __init__(self, content):
        self.root = "/tmp/mock_hmx"
        self.index = Index()
        self.resolver = Resolver(self.index)
        self.workspace = Workspace({MODEL_URI: content})
        model = self.index.entry("purchaseorder")
        model.sites.append(Loc("hmx/module/basic/demo/models/purchase_order.py", 5, 0))
        model.declared["expected_date"] = Loc("models/purchase_order.py", 12, 4)
        model.methods["action_confirm"] = Loc("models/purchase_order.py", 20, 4)
        self.index.xmlids.entries["demo.model_purchaseorder"] = XmlIdEntry(
            xmlid="demo.model_purchaseorder", model="purchaseorder",
            name="Purchase Order", loc=Loc("data/models.xml", 3, 0))


def test_model_child_ref_navigates_to_python_model():
    content = '''<hmx><record id="workflow" model="approvalrule">
        <field name="model_id" ref="demo.model_purchaseorder"/>
        <field name="model_id" ref="demo.model_purchaseorder"/>
    </record></hmx>'''
    server = Server(content)
    lines = content.splitlines()
    line_number = next(i for i, line in enumerate(lines)
                       if "demo.model_purchaseorder" in line)
    col = lines[line_number].index("demo.model_purchaseorder") + 2
    context = resolve_xml_cursor(content, line_number + 1, col, server.resolver)

    assert context is not None
    assert context.kind == "model"
    assert context.value == "purchaseorder"
    position = types.Position(line=line_number, character=col)
    assert len(resolve_definition(server, MODEL_URI, position)) == 1
    assert resolve_hover(server, MODEL_URI, position) is not None
    assert resolve_references(server, MODEL_URI, position)
    labels = [item.label for item in resolve_completion(server, MODEL_URI, position).items]
    assert "demo.model_purchaseorder" in labels
    item = next(item for item in resolve_completion(server, MODEL_URI, position).items
                 if item.label == "demo.model_purchaseorder")
    assert item.insert_text == "demo.model_purchaseorder"


def test_object_button_navigates_to_python_method():
    content = '''<hmx><record id="view" model="baseuiview">
        <field name="model">purchaseorder</field>
        <field name="arch" type="xml"><form>
            <button name="action_confirm" type="object"/>
        </form></field>
    </record></hmx>'''
    server = Server(content)
    line = content.splitlines()[3]
    col = line.index("action_confirm") + 2
    position = types.Position(line=3, character=col)
    context = resolve_xml_cursor(content, 4, col, server.resolver)

    assert context is not None
    assert context.kind == "method"
    assert context.active_model == "purchaseorder"
    assert len(resolve_definition(server, MODEL_URI, position)) == 1
    assert resolve_hover(server, MODEL_URI, position) is not None


def test_unknown_object_button_is_diagnostic():
    content = '''<hmx><record id="view" model="baseuiview">
        <field name="model">purchaseorder</field>
        <field name="arch" type="xml"><form>
            <button name="missing_action" type="object"/>
        </form></field>
    </record></hmx>'''
    server = Server(content)
    messages = [d.message for d in compute_diagnostics(server, MODEL_URI)]
    assert [message for message in messages if "missing_action" in message]
