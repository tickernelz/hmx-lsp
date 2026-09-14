from __future__ import annotations

from lsprotocol import types

from hmx_core.index import build
from hmx_core.resolve import Resolver
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.hover import resolve_hover

SOURCE_ORDER = '''from hmx import models


class PurchaseOrder(models.Model):
    class Meta:
        name = "purchaseorder"

    def close(self):
        for transfer in self.transfers:
            transfer.check(self)
'''

SOURCE_LINE = '''from hmx import models


class PurchaseOrderLine(models.Model):
    class Meta:
        name = "purchaseorderline"

    order = models.ForeignKey("purchaseorder", related_name="order_line_ids")
    qty_remaining = models.FloatField()

    def rounding(self):
        return self.env["baseuom"]
'''

SOURCE_TRANSFER = '''from hmx import models


class Transfer(models.Model):
    class Meta:
        name = "transfer"

    order = models.ForeignKey("purchaseorder", related_name="transfers")

    def lines_for(self, order):
        return order.order_line_ids.filtered(lambda line: line.qty_remaining)

    def check(self, order):
        stock_lines = self.lines_for(order=order)
        for line in stock_lines:
            rounding = line.rounding()
            remaining = line.qty_remaining
            return remaining
'''


class Workspace:
    def get_text_document(self, uri):
        return None


class Server:
    pass


def setup(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    files = {
        "order.py": SOURCE_ORDER,
        "line.py": SOURCE_LINE,
        "transfer.py": SOURCE_TRANSFER,
    }
    for name, source in files.items():
        (model_dir / name).write_text(source)
    index = build(str(tmp_path), workers=1)
    server = Server()
    server.root = str(tmp_path)
    server.index = index
    server.resolver = Resolver(index)
    server.workspace = Workspace()
    path = model_dir / "transfer.py"
    return server, path, path_to_uri(str(path))


def test_method_parameter_and_local_return_chain_resolves_line_field(tmp_path):
    server, path, uri = setup(tmp_path)
    source = SOURCE_TRANSFER
    lines = source.splitlines()
    line = next(i for i, text in enumerate(lines) if "remaining = line.qty_remaining" in text)
    col = lines[line].rindex("qty_remaining") + 2
    position = types.Position(line=line, character=col)
    context = resolve_py_cursor(source, line + 1, col, server.resolver)

    assert context is not None
    assert context.kind == "field"
    assert context.active_model == "purchaseorderline"
    definitions = resolve_definition(server, uri, position)
    assert len(definitions) == 1
    assert definitions[0].uri.endswith("line.py")
    assert resolve_hover(server, uri, position) is not None


def test_method_returning_a_line_model_resolves_method_calls(tmp_path):
    server, path, uri = setup(tmp_path)
    source = SOURCE_TRANSFER
    lines = source.splitlines()
    line = next(i for i, text in enumerate(lines) if "line.rounding()" in text)
    col = lines[line].rindex("rounding") + 2
    position = types.Position(line=line, character=col)
    context = resolve_py_cursor(source, line + 1, col, server.resolver)

    assert context is not None
    assert context.kind == "method"
    assert context.active_model == "purchaseorderline"
    assert len(resolve_definition(server, uri, position)) == 1


def test_nested_class_returns_do_not_change_outer_method_type(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    path = model_dir / "nested.py"
    path.write_text("""from hmx import models


class Outer(models.Model):
    class Meta:
        name = "outer"

    def choose(self):
        class Inner:
            def nested(self):
                return self.env["purchaseorderline"]
        return None
""")
    index = build(str(tmp_path), workers=1)
    resolver = Resolver(index)

    from hmx_core.locals import method_result_model

    assert method_result_model("outer", "choose", resolver) is None
