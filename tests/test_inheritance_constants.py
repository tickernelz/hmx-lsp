from __future__ import annotations

from hmx_core.index import build
from hmx_core.resolve import Resolver
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics
from lsprotocol import types


def test_module_constant_model_name_and_inherit_resolve_consistently(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    source = '''MODEL_NAME = "purchaseorder"

from hmx import api, models


class PurchaseOrder(models.Model):
    class Meta:
        name = MODEL_NAME

    expected_date = models.DateTimeField()


class PurchaseInsight(models.Model):
    class Meta:
        inherit = MODEL_NAME

    @api.depends("expected_date")
    def _compute(self):
        for order in self:
            value = order.expected_date
'''
    path = model_dir / "purchase.py"
    path.write_text(source)
    index = build(str(tmp_path))
    resolver = Resolver(index)
    uri = path_to_uri(str(path))
    lines = source.splitlines()
    line = next(i for i, text in enumerate(lines) if "order.expected_date" in text)
    col = lines[line].index("expected_date") + 2
    context = resolve_py_cursor(source, line + 1, col, resolver)

    class Server:
        pass

    server = Server()
    server.root = str(tmp_path)
    server.index = index
    server.resolver = resolver
    server.workspace = None
    position = types.Position(line=line, character=col)

    assert set(index.models) == {"purchaseorder"}
    assert context is not None
    assert context.active_model == "purchaseorder"
    assert len(resolve_definition(server, uri, position)) == 1
    assert not [d for d in compute_diagnostics(server, uri) if "expected_date" in d.message]


def test_class_constant_inherit_aliases_the_parent_model(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    source = '''from hmx import models


class PurchaseOrder(models.Model):
    class Meta:
        name = "purchaseorder"

    expected_date = models.DateTimeField()


class PurchaseInsight(models.Model):
    INHERITED_MODEL = "purchaseorder"

    class Meta:
        inherit = INHERITED_MODEL

    def _compute(self):
        for order in self:
            value = order.expected_date
'''
    path = model_dir / "purchase.py"
    path.write_text(source)
    index = build(str(tmp_path))
    resolver = Resolver(index)
    line = next(i for i, text in enumerate(source.splitlines()) if "order.expected_date" in text)
    col = source.splitlines()[line].index("expected_date") + 2
    context = resolve_py_cursor(source, line + 1, col, resolver)

    assert set(index.models) == {"purchaseorder"}
    assert context is not None
    assert context.active_model == "purchaseorder"
