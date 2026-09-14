from __future__ import annotations

import ast

import pytest

from hmx_core import pysource
from hmx_core.pysource import extract, parse_source

SOURCE = b'''from hmx import models


class Parent(models.Model):
    class Meta:
        name = "parent"

    value = models.IntegerField()

    def recover(self, value):
        try:
            return value
        except ValueError, TypeError:
            return 0
'''


def test_parser_accepts_hmx_exception_group_syntax():
    tree = parse_source(SOURCE)
    classes = [node.name for node in tree.body if hasattr(node, "name")]
    assert "Parent" in classes


def test_extractor_keeps_models_after_hmx_exception_group_syntax():
    declarations, _ = extract(SOURCE, "models/parent.py", "demo")
    assert [decl.model for decl in declarations] == ["parent"]
    assert declarations[0].fields[0].name == "value"


def test_hmx_parent_and_extension_survive_python_314_exception_syntax():
    source = b"""from hmx import api, models


class PurchaseOrder(models.Model):
    class Meta:
        name = "purchaseorder"

    status = models.CharField()
    quotation_expiry_date = models.DateTimeField()
    expected_date = models.DateTimeField()
    is_purchase_order = models.BooleanField()
    is_direct_purchase_order = models.BooleanField()
    received_percentage = models.FloatField()

    def normalize(self):
        try:
            return self.status
        except ValueError, TypeError:
            return ""


class PurchaseOrderExtension(models.Model):
    class Meta:
        inherit = "purchaseorder"

    @api.depends(
        "status",
        "quotation_expiry_date",
        "expected_date",
        "is_purchase_order",
        "is_direct_purchase_order",
        "received_percentage",
    )
    def _compute_quick_view_insight(self):
        for order in self:
            value = order.received_percentage
"""
    declarations, _ = extract(source, "models/purchase_order.py", "demo")
    assert [declaration.model for declaration in declarations] == [
        "purchaseorder", "purchaseorder"
    ]
    names = {field.name for declaration in declarations for field in declaration.fields}
    assert {
        "status", "quotation_expiry_date", "expected_date", "is_purchase_order",
        "is_direct_purchase_order", "received_percentage",
    } <= names

def test_fallback_path_is_exercised_and_preserves_strings_and_columns(monkeypatch):
    source = 'value = """\nexcept ValueError, TypeError:\n"""\ntry:\n    result = 1\nexcept ValueError, TypeError: result = 2\n'
    original = pysource.ast.parse
    calls = []

    def force_retry(text, *args, **kwargs):
        if not calls:
            calls.append(text)
            raise SyntaxError("forced fallback")
        calls.append(text)
        return original(text, *args, **kwargs)

    monkeypatch.setattr(pysource.ast, "parse", force_retry)
    tree = pysource.parse_source(source)
    values = [node.value for node in ast.walk(tree)
              if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    result = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.Name) and node.id == "result"
                  and node.lineno == 6)

    assert len(calls) == 2
    assert any("except ValueError, TypeError:" in value for value in values)
    assert result.col_offset == source.splitlines()[5].index("result")


def test_fallback_restores_utf8_byte_columns(monkeypatch):
    source = "try:\n    result = 1\nexcept Érror, TypeError: result = 2\n"
    original = pysource.ast.parse
    calls = []

    def force_retry(text, *args, **kwargs):
        if not calls:
            calls.append(text)
            raise SyntaxError("forced fallback")
        calls.append(text)
        return original(text, *args, **kwargs)

    monkeypatch.setattr(pysource.ast, "parse", force_retry)
    tree = pysource.parse_source(source)
    result = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.Name) and node.id == "result"
                  and node.lineno == 3)
    expected = len(source.splitlines()[2].split("result")[0].encode("utf-8"))

    assert result.col_offset == expected
