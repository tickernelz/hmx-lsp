from __future__ import annotations

import time
from lsprotocol import types

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_ls.features.completion import resolve_completion
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.hover import resolve_hover


class MockWorkspace:
    def __init__(self, docs: dict[str, str]):
        self.docs = docs

    def get_text_document(self, uri: str):
        if uri in self.docs:
            class MockDoc:
                source = self.docs[uri]
            return MockDoc()
        return None


class MockServer:
    def __init__(self, root: str, docs: dict[str, str]):
        self.root = root
        self.index = Index()
        self.resolver = Resolver(self.index)
        self.workspace = MockWorkspace(docs)


def test_performance_sla():
    root = "/tmp/mock_hmx"
    docs = {}
    server = MockServer(root, docs)

    for i in range(2000):
        mname = f"model_{i}"
        entry = server.index.entry(mname)
        entry.sites.append(Loc(f"models/mod_{i}.py", 10, 0))
        for j in range(20):
            entry.declared[f"field_{j}"] = Loc(f"models/mod_{i}.py", 20 + j, 4)
            if j == 0:
                entry.comodel[f"field_{j}"] = f"model_{(i + 1) % 2000}"

    xml_content = """<record id="view_large" model="baseuiview">
    <field name="model">model_500</field>
    <field name="arch" type="xml">
        <form>
            <field name="field_0" />
        </form>
    </field>
</record>"""
    xml_uri = "file:///tmp/mock_hmx/views/large_view.xml"
    docs[xml_uri] = xml_content

    pos = types.Position(line=4, character=28)

    t0 = time.perf_counter()
    for _ in range(50):
        locs = resolve_definition(server, xml_uri, pos)
    dt_def = (time.perf_counter() - t0) / 50
    assert len(locs) == 1
    assert dt_def < 0.01

    t0 = time.perf_counter()
    for _ in range(50):
        h = resolve_hover(server, xml_uri, pos)
    dt_hover = (time.perf_counter() - t0) / 50
    assert h is not None
    assert dt_hover < 0.01

    t0 = time.perf_counter()
    for _ in range(50):
        comp = resolve_completion(server, xml_uri, pos)
    dt_comp = (time.perf_counter() - t0) / 50
    assert len(comp.items) == 20
    assert dt_comp < 0.01

    py_update = b"""class Model500(models.Model):
    class Meta:
        name = "model_500"

    field_new = models.CharField(max_length=50)
"""
    t0 = time.perf_counter()
    affected = server.index.update_file("models/mod_500.py", py_update)
    server.resolver.invalidate(affected)
    dt_update = time.perf_counter() - t0
    assert "model_500" in affected
    assert dt_update < 0.02
