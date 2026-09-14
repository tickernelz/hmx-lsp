from __future__ import annotations

from lsprotocol import types

from hmx_core.index import build
from hmx_core.resolve import Resolver
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.features.completion import resolve_completion
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.hover import resolve_hover
from hmx_ls.features.references import resolve_references
from hmx_ls.features.rename import prepare_rename, resolve_rename

SOURCE = '''from hmx import api, models


class CreditLimitRequest(models.Model):
    class Meta:
        name = "creditlimitrequest"

    company_id = models.ForeignKey("basecompany")

    def _get_credit_limit_line(self):
        return self.env["basepartnercreditlimit"].search([])

    def _get_company_from_customer(self, partner):
        return self.env["basecompany"]

    def _get_credit_snapshot_values(self):
        self.ensure_one()
        credit_line = self._get_credit_limit_line()
        current_limit = credit_line.credit_limit
        credit_used = credit_line.credit_used
        return {"current_credit_limit": current_limit, "credit_used": credit_used}

    def _onchange_credit_context(self):
        for rec in self:
            rec.company_id = rec._get_company_from_customer(rec.partner_id)
            values = rec._get_credit_snapshot_values()
            message = "rec._get_credit_snapshot_values()"


class BasePartnerCreditLimit(models.Model):
    class Meta:
        name = "basepartnercreditlimit"

    credit_limit = models.FloatField()
    credit_used = models.FloatField()
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
    pass


def setup(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    path = model_dir / "credit.py"
    path.write_text(SOURCE)
    index = build(str(tmp_path), workers=1)
    uri = path_to_uri(str(path))
    server = Server()
    server.root = str(tmp_path)
    server.index = index
    server.resolver = Resolver(index)
    server.workspace = Workspace({uri: SOURCE})
    return server, path, uri


def position(token, receiver):
    lines = SOURCE.splitlines()
    line = next(i for i, text in enumerate(lines) if f"{receiver}.{token}" in text)
    col = lines[line].index(f"{receiver}.{token}") + len(receiver) + 2
    return types.Position(line=line, character=col)


def test_credit_line_fields_resolve_from_method_return_model(tmp_path):
    server, path, uri = setup(tmp_path)
    for field in ("credit_limit", "credit_used"):
        pos = position(field, "credit_line")
        ctx = resolve_py_cursor(SOURCE, pos.line + 1, pos.character, server.resolver)
        assert ctx is not None
        assert ctx.kind == "field"
        assert ctx.active_model == "basepartnercreditlimit"
        assert len(resolve_definition(server, uri, pos)) == 1
        assert resolve_hover(server, uri, pos) is not None
        assert path.exists()


def test_credit_methods_resolve_as_methods_not_fields(tmp_path):
    server, _, uri = setup(tmp_path)
    for method in ("_get_company_from_customer", "_get_credit_snapshot_values"):
        pos = position(method, "rec")
        ctx = resolve_py_cursor(SOURCE, pos.line + 1, pos.character, server.resolver)
        assert ctx is not None
        assert ctx.kind == "method"
        assert ctx.active_model == "creditlimitrequest"
        assert len(resolve_definition(server, uri, pos)) == 1
        assert resolve_hover(server, uri, pos) is not None
        references = resolve_references(server, uri, pos)
        assert len(references) >= 2
        assert prepare_rename(server, uri, pos) is not None
        edit = resolve_rename(server, uri, pos, "renamed_method")
        assert edit is not None
        edits = [item for values in edit.changes.values() for item in values]
        assert sum(item.new_text == "renamed_method" for item in edits) == 2


def test_credit_method_completion_works_while_typing(tmp_path):
    server, _, uri = setup(tmp_path)
    source = SOURCE.replace("rec._get_company_from_customer", "rec._get_")
    server.workspace = Workspace({uri: source})
    lines = source.splitlines()
    line = next(i for i, text in enumerate(lines) if "rec._get_" in text)
    pos = types.Position(line=line, character=lines[line].index("rec._get_") + len("rec._get_"))
    ctx = resolve_py_cursor(source, pos.line + 1, pos.character, server.resolver)
    labels = [item.label for item in resolve_completion(server, uri, pos).items]

    assert ctx is not None
    assert ctx.kind == "field_prefix"
    assert ctx.active_model == "creditlimitrequest"
    assert "_get_company_from_customer" in labels
    assert "_get_credit_snapshot_values" in labels


def test_cyclic_recordset_methods_do_not_recurse_forever(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    path = model_dir / "cycle.py"
    path.write_text("""from hmx import models


class Cycle(models.Model):
    class Meta:
        name = "cycle"

    def alpha(self):
        return self.beta()

    def beta(self):
        return self.alpha()
""")
    index = build(str(tmp_path), workers=1)
    resolver = Resolver(index)

    from hmx_core.locals import method_result_model

    assert method_result_model("cycle", "alpha", resolver) is None


def test_divergent_recordset_methods_decline_inference(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    path = model_dir / "divergent.py"
    path.write_text("""from hmx import models


class ModelA(models.Model):
    class Meta:
        name = "modela"
    amount_a = models.FloatField()


class ModelB(models.Model):
    class Meta:
        name = "modelb"
    amount_b = models.FloatField()


class Carrier(models.Model):
    class Meta:
        name = "carrier"

    def choose(self, flag):
        if flag:
            return self.env["modela"]
        return self.env["modelb"]
""")
    index = build(str(tmp_path), workers=1)
    resolver = Resolver(index)

    from hmx_core.locals import method_result_model

    assert method_result_model("carrier", "choose", resolver) is None


def test_conditional_recordset_methods_decline_conflicting_models(tmp_path):
    model_dir = tmp_path / "hmx" / "module" / "basic" / "demo" / "models"
    model_dir.mkdir(parents=True)
    path = model_dir / "conditional.py"
    path.write_text("""from hmx import models


class ModelA(models.Model):
    class Meta:
        name = "modela"


class ModelB(models.Model):
    class Meta:
        name = "modelb"


class Carrier(models.Model):
    class Meta:
        name = "carrier"

    def choose(self, flag):
        return self.env["modela"] if flag else self.env["modelb"]
""")
    index = build(str(tmp_path), workers=1)
    resolver = Resolver(index)

    from hmx_core.locals import method_result_model

    assert method_result_model("carrier", "choose", resolver) is None
