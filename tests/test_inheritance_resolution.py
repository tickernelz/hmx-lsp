from __future__ import annotations

import os

from lsprotocol import types

from hmx_core.index import build
from hmx_core.resolve import Resolver
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.features.completion import resolve_completion
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics
from hmx_ls.features.hover import resolve_hover
from hmx_ls.features.references import resolve_references
from hmx_ls.features.rename import prepare_rename, resolve_rename

SOURCE = '''from hmx import api, models


class PurchaseOrder(models.Model):
    class Meta:
        name = "purchaseorder"

    expected_date = models.DateTimeField()
    is_purchase_order = models.BooleanField()


class PurchaseInsight(models.Model):
    class Meta:
        inherit = "purchaseorder"

    @api.depends("expected_date", "nosuchfield")
    def _compute_quick_view_insight(self):
        for order in self.filtered(lambda record: record.is_purchase_order):
            received_percentage = order.expected_date
            broken = order.nosuchfield
'''


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
    def __init__(self, root, uri, index, source):
        self.root = root
        self.index = index
        self.resolver = Resolver(index)
        self.workspace = Workspace({uri: source})


def _repo(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    path = model_dir / "purchase.py"
    path.write_text(SOURCE)
    return path


def _server(tmp_path):
    path = _repo(tmp_path)
    root = str(tmp_path)
    uri = path_to_uri(str(path))
    return Server(root, uri, build(root), SOURCE), path, uri


def _attribute_position(path, token, receiver="order"):
    lines = SOURCE.splitlines()
    line = next(i for i, text in enumerate(lines) if f"{receiver}.{token}" in text)
    col = lines[line].index(f"{receiver}.{token}") + len(receiver) + 2
    return types.Position(line=line, character=col)


def test_inherited_model_merges_parent_fields(tmp_path):
    server, _, _ = _server(tmp_path)
    assert set(server.index.models) == {"purchaseorder"}
    assert {"expected_date", "is_purchase_order"} <= set(
        server.resolver.fields("purchaseorder")
    )
    assert "_compute_quick_view_insight" in server.resolver.methods("purchaseorder")


def test_inherited_loop_attribute_supports_all_navigation_features(tmp_path):
    server, path, uri = _server(tmp_path)
    position = _attribute_position(path, "expected_date")
    context = resolve_py_cursor(SOURCE, position.line + 1, position.character, server.resolver)

    assert context is not None
    assert context.kind == "field"
    assert context.value == "expected_date"
    assert context.active_model == "purchaseorder"
    assert resolve_hover(server, uri, position) is not None
    assert len(resolve_definition(server, uri, position)) == 1
    assert resolve_references(server, uri, position)
    assert prepare_rename(server, uri, position) is not None
    assert resolve_rename(server, uri, position, "planned_date") is not None


def test_inherited_api_depends_uses_parent_fields_and_reports_unknowns(tmp_path):
    server, path, uri = _server(tmp_path)
    diagnostics = compute_diagnostics(server, uri)
    by_message = {diagnostic.message for diagnostic in diagnostics}

    assert not [message for message in by_message if "expected_date" in message]
    assert [message for message in by_message if "nosuchfield" in message]
    assert not [message for message in by_message if "purchaseorder" not in message]
    assert path.exists()


def test_inherited_model_completion_works_before_attribute_is_complete(tmp_path):
    server, path, uri = _server(tmp_path)
    incomplete = SOURCE.replace("order.expected_date", "order.")
    server.workspace = Workspace({uri: incomplete})
    lines = incomplete.splitlines()
    line = next(i for i, text in enumerate(lines) if "order." in text)
    position = types.Position(line=line, character=lines[line].index("order.") + len("order."))
    context = resolve_py_cursor(incomplete, position.line + 1, position.character, server.resolver)
    completion = resolve_completion(server, uri, position)
    labels = [item.label for item in completion.items]

    assert context is not None
    assert context.kind == "field_prefix"
    assert context.active_model == "purchaseorder"
    assert "expected_date" in labels
    assert "is_purchase_order" in labels
    assert path.exists()
