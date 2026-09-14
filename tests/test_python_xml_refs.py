from __future__ import annotations

from lsprotocol import types

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_core.xmlids import XmlIdEntry
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.cursor.py_cursor import resolve_py_cursor
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics
from hmx_ls.features.hover import resolve_hover
from hmx_ls.features.references import resolve_references

URI = "file:///tmp/mock_hmx/models/security.py"


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
    def __init__(self, source):
        self.root = "/tmp/mock_hmx"
        self.index = Index()
        self.resolver = Resolver(self.index)
        self.workspace = Workspace({URI: source})
        model = self.index.entry("securitymodel")
        model.sites.append(Loc("models/security.py", 1, 0))
        model.methods["check"] = Loc("models/security.py", 9, 4)
        self.index.xmlids.entries["base.group_user"] = XmlIdEntry(
            xmlid="base.group_user", model="basegroup", name="Users",
            loc=Loc("security/groups.xml", 2, 0),
        )
        self.index.xmlids.entries["base.known_record"] = XmlIdEntry(
            xmlid="base.known_record", model="baserecord", name="Record",
            loc=Loc("data/records.xml", 3, 0),
        )


def test_env_ref_and_has_group_are_xmlid_contexts():
    source = '''from hmx import api, models


class SecurityModel(models.Model):
    class Meta:
        name = "securitymodel"

    GROUP_XMLID = "base.group_user"

    @api.model
    def check(self):
        user = self.env.user
        return user.has_group("base.group_user") and self.env.ref("base.known_record")

    def through_record(self, record):
        return record.env.ref("base.known_record")
'''
    server = Server(source)
    lines = source.splitlines()
    probes = [(i, "base.group_user") for i, line in enumerate(lines)
              if "base.group_user" in line]
    probes += [(i, "base.known_record") for i, line in enumerate(lines)
               if "record.env.ref" in line]
    probes.append((next(i for i, line in enumerate(lines) if "GROUP_XMLID" in line), "GROUP_XMLID"))

    for line, token in probes:
        col = lines[line].index(token) + 1
        context = resolve_py_cursor(source, line + 1, col, server.resolver)
        assert context is not None
        assert context.kind == "xmlid"
        assert context.value in ("base.group_user", "base.known_record")


def test_python_xmlid_definition_and_hover_are_cross_layer():
    source = '''from hmx import api, models


class SecurityModel(models.Model):
    class Meta:
        name = "securitymodel"

    @api.model
    def check(self):
        return self.env.ref("base.known_record")
'''
    server = Server(source)
    line = next(i for i, text in enumerate(source.splitlines()) if "base.known_record" in text)
    col = source.splitlines()[line].index("base.known_record") + 1
    position = types.Position(line=line, character=col)

    locations = resolve_definition(server, URI, position)
    hover = resolve_hover(server, URI, position)
    assert len(locations) == 1
    assert locations[0].uri.endswith("data/records.xml")
    assert hover is not None
    assert resolve_references(server, URI, position)


def test_has_group_and_env_ref_unknown_values_are_diagnosed():
    source = '''from hmx import api, models


class SecurityModel(models.Model):
    class Meta:
        name = "securitymodel"

    @api.model
    def check(self):
        user = self.env.user
        return user.has_group("base.missing_group") and self.env.ref("base.missing_record")
'''
    server = Server(source)
    diagnostics = compute_diagnostics(server, URI)
    codes = {diagnostic.code for diagnostic in diagnostics}
    messages = [diagnostic.message for diagnostic in diagnostics]

    assert "hmx-unknown-group" in codes
    assert "hmx-unknown-xmlid" in codes
    assert any("base.missing_group" in message for message in messages)
    assert any("base.missing_record" in message for message in messages)


def test_field_compute_string_navigates_to_the_method():
    source = """from hmx import api, models


class SecurityModel(models.Model):
    class Meta:
        name = "securitymodel"

    is_customer = models.BooleanField(compute="_compute_is_customer", store=True)

    def _compute_is_customer(self):
        return True
"""
    server = Server(source)
    line = next(i for i, text in enumerate(source.splitlines())
                if "_compute_is_customer" in text)
    col = source.splitlines()[line].index("_compute_is_customer") + 2
    position = types.Position(line=line, character=col)
    context = resolve_py_cursor(source, line + 1, col, server.resolver)

    assert context is not None
    assert context.kind == "method"
    assert context.active_model == "securitymodel"


def test_arbitrary_ref_methods_are_not_xmlid_contexts_or_diagnostics():
    source = """from hmx import models


class SecurityModel(models.Model):
    class Meta:
        name = "securitymodel"

    def check(self, formatter, parser):
        formatter.ref("base.missing_record")
        parser.xmlid_to_res_id("base.missing_record")
        parser.env["basemodeldata"].xmlid_to_res_id("base.missing_record")
        return parser.has_group("base.missing_group")
"""
    server = Server(source)
    lines = source.splitlines()
    for needle in ("base.missing_record", "base.missing_group"):
        line = next(i for i, text in enumerate(lines) if needle in text)
        col = lines[line].index(needle) + 1
        context = resolve_py_cursor(source, line + 1, col, server.resolver)
        assert context is None or context.kind != "xmlid"
    diagnostics = compute_diagnostics(server, URI)
    assert not diagnostics


def test_bare_call_strings_are_not_treated_as_xmlids():
    source = 'print("hello")\n'
    context = resolve_py_cursor(source, 1, source.index("hello") + 1)

    assert context is not None
    assert context.kind == "string"
    assert context.value == "hello"


def test_dynamic_action_xmlid_keeps_trailing_identifier_characters():
    content = '<hmx><record id="v" model="baseuiview"><field name="arch"><form><button name="%(hr.actiond)d" type="action"/></form></field></record></hmx>'
    server = Server(content)
    line = content.splitlines()[0]
    col = line.index("hr.actiond") + 1
    context = resolve_xml_cursor(content, 1, col, server.resolver)

    assert context is not None
    assert context.kind == "xmlid"
    assert context.value == "hr.actiond"
