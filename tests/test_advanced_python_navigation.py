from __future__ import annotations

from lsprotocol import types

from hmx_core.index import build
from hmx_core.resolve import Resolver
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.hover import resolve_hover

SOURCE = '''from typing import Any, cast
from hmx import models


class BasePayment(models.Model):
    class Meta:
        name = "paymentmethod"

    def confirm(self):
        return True


class Payment(models.Model):
    class Meta:
        inherit = "paymentmethod"

    journal = models.ForeignKey("core_accounting.accountjournal")

    def read_bank(self):
        journal = cast(Any, self.journal)
        bank_account = getattr(journal, "bank_account_id", None) if journal else None
        return bank_account.acc_number

    def check_type(self):
        return self.journal.type != self.method_type

    def confirm(self):
        return super().confirm()


class Journal(models.Model):
    class Meta:
        name = "accountjournal"

    bank_account_id = models.ForeignKey("basepartnerbank")
    type = models.CharField()


class Bank(models.Model):
    class Meta:
        name = "basepartnerbank"

    acc_number = models.CharField()
'''


class Workspace:
    def get_text_document(self, uri):
        return None


class Server:
    pass


def setup(tmp_path):
    directory = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    directory.mkdir(parents=True)
    path = directory / "payment.py"
    path.write_text(SOURCE)
    index = build(str(tmp_path), workers=1)
    server = Server()
    server.root = str(tmp_path)
    server.index = index
    server.resolver = Resolver(index)
    server.workspace = Workspace()
    return server, path, path_to_uri(str(path))


def test_getattr_and_cast_preserve_receiver_models(tmp_path):
    server, path, uri = setup(tmp_path)
    lines = SOURCE.splitlines()
    probes = [("bank_account_id", "bank_account_id"),
              ("acc_number", "bank_account.acc_number"),
              ("type", "self.journal.type")]
    for token, needle in probes:
        line = next(i for i, text in enumerate(lines) if needle in text)
        col = lines[line].index(token) + 2
        position = types.Position(line=line, character=col)
        context = resolve_py_cursor(SOURCE, line + 1, col, server.resolver)
        assert context is not None
        assert context.kind == "field"
        assert len(resolve_definition(server, uri, position)) == 1
        assert resolve_hover(server, uri, position) is not None
        assert path.exists()


def test_super_method_resolves_to_inherited_method(tmp_path):
    server, path, uri = setup(tmp_path)
    lines = SOURCE.splitlines()
    line = next(i for i, text in enumerate(lines) if "super().confirm()" in text)
    col = lines[line].index("confirm") + 2
    position = types.Position(line=line, character=col)
    context = resolve_py_cursor(SOURCE, line + 1, col, server.resolver)

    assert context is not None
    assert context.kind == "method"
    assert context.active_model == "paymentmethod"
    assert context.method_loc is not None
    assert context.method_loc.line == 9
    locations = resolve_definition(server, uri, position)
    assert len(locations) == 1
    assert locations[0].uri.endswith("payment.py")
    assert locations[0].range.start.line == 8


def test_qualified_foreign_key_string_resolves_to_model(tmp_path):
    server, path, uri = setup(tmp_path)
    lines = SOURCE.splitlines()
    line = next(i for i, text in enumerate(lines) if "core_accounting.accountjournal" in text)
    col = lines[line].index("core_accounting.accountjournal") + 2
    position = types.Position(line=line, character=col)
    context = resolve_py_cursor(SOURCE, line + 1, col, server.resolver)

    assert context is not None
    assert context.kind == "model"
    assert context.value == "accountjournal"
    assert context.secondary_value == "core_accounting.accountjournal"
    assert len(resolve_definition(server, uri, position)) == 1
    assert resolve_hover(server, uri, position) is not None


def test_incremental_update_refreshes_same_model_method_sites(tmp_path):
    server, path, _ = setup(tmp_path)
    entry = server.index.models["paymentmethod"]
    assert len(entry.method_sites["confirm"]) == 2
    updated = SOURCE.replace(
        "    def confirm(self):\n        return super().confirm()",
        "    def finish(self):\n        return super().confirm()",
    )
    path.write_text(updated)
    relative = path.relative_to(tmp_path).as_posix()
    server.index.update_file(relative, updated.encode("utf-8"))

    assert len(entry.method_sites["confirm"]) == 1
    assert "finish" in entry.method_sites
