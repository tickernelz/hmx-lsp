from __future__ import annotations

import os

from lsprotocol import types

from hmx_core.index import Index
from hmx_core.resolve import Resolver
from hmx_core.styles import scan_styles
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.cursor.xml_cursor import resolve_xml_cursor
from hmx_ls.features.completion import resolve_completion
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics

MANIFEST = '''{
    "name": "demo",
    "assets": {
        "webx.assets_backend": [
            "static/js/live.js",
            "static/js/*.js",
            "static/css/ghost.css",
            "static/css/*.css",
        ],
    },
}
'''


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
    def __init__(self, root, docs, styles=None):
        self.root = str(root)
        self.index = Index()
        self.resolver = Resolver(self.index)
        self.workspace = MockWorkspace(docs)
        self.styles = styles


def _demo_module(tmp_path):
    mod = tmp_path / "hmx" / "module" / "basic" / "demo"
    (mod / "static" / "js").mkdir(parents=True)
    (mod / "static" / "css").mkdir(parents=True)
    (mod / "static" / "js" / "live.js").write_text("const a = 1;\n")
    (mod / "__hmx__.py").write_text(MANIFEST)
    return mod


def test_dead_asset_pattern_is_reported_and_live_one_is_not(tmp_path):
    mod = _demo_module(tmp_path)
    manifest = str(mod / "__hmx__.py")
    uri = path_to_uri(manifest)
    server = MockServer(tmp_path, {uri: MANIFEST})

    found = {d.message for d in compute_diagnostics(server, uri)}
    codes = {d.code for d in compute_diagnostics(server, uri)}

    assert codes == {"hmx-dead-asset"}
    assert any("static/css/ghost.css" in m for m in found)
    assert any("static/css/*.css" in m for m in found)
    assert not [m for m in found if "static/js/live.js" in m]
    assert not [m for m in found if "static/js/*.js" in m]


def test_dead_asset_diagnostic_points_at_the_pattern_line(tmp_path):
    mod = _demo_module(tmp_path)
    uri = path_to_uri(str(mod / "__hmx__.py"))
    server = MockServer(tmp_path, {uri: MANIFEST})
    lines = MANIFEST.splitlines()
    for diag in compute_diagnostics(server, uri):
        text = lines[diag.range.start.line]
        assert "ghost.css" in text or "*.css" in text


def test_recursive_glob_in_manifest_counts_nested_files(tmp_path):
    mod = _demo_module(tmp_path)
    nested = mod / "static" / "vue" / "views" / "fields"
    nested.mkdir(parents=True)
    (nested / "deep.vue").write_text("<template/>\n")
    (mod / "static" / "vue" / "top.vue").write_text("<template/>\n")
    body = MANIFEST.replace('"static/css/*.css",',
                            '"static/css/*.css",\n            "static/vue/**/*.vue",')
    (mod / "__hmx__.py").write_text(body)
    uri = path_to_uri(str(mod / "__hmx__.py"))
    server = MockServer(tmp_path, {uri: body})
    messages = {d.message for d in compute_diagnostics(server, uri)}
    assert not [m for m in messages if "static/vue/**/*.vue" in m]


def test_class_cursor_isolates_the_token_under_the_caret():
    xml = '<hmx><form><div class="card ca-amount wide"/></form></hmx>'
    base = xml.index("card")
    got = [resolve_xml_cursor(xml, 1, base + offset) for offset in (1, 6, 17)]
    assert [c.kind for c in got] == ["cssclass"] * 3
    assert [c.value for c in got] == ["card", "ca-amount", "wide"]


def test_css_class_definition_and_completion(tmp_path):
    mod = tmp_path / "hmx" / "module" / "basic" / "demo" / "static" / "css"
    mod.mkdir(parents=True)
    (mod / "a.css").write_text(".card { color: red; }\n.cart { color: blue; }\n")
    (mod / "b.css").write_text(".card { margin: 1.5rem; }\n")
    styles = scan_styles(str(tmp_path))

    xml = '<hmx><form><div class="card"/></form></hmx>'
    uri = path_to_uri(str(tmp_path / "hmx" / "module" / "basic" / "demo" / "views" / "v.xml"))
    server = MockServer(tmp_path, {uri: xml}, styles=styles)
    position = types.Position(line=0, character=xml.index("card") + 1)

    locations = resolve_definition(server, uri, position)
    assert len(locations) == 2
    assert {os.path.basename(loc.uri) for loc in locations} == {"a.css", "b.css"}

    caret = types.Position(line=0, character=xml.index("card") + 2)
    labels = [item.label for item in resolve_completion(server, uri, caret).items]
    assert "card" in labels and "cart" in labels
    assert "5rem" not in labels

    exact = types.Position(line=0, character=xml.index("card") + 4)
    narrowed = [item.label for item in resolve_completion(server, uri, exact).items]
    assert narrowed == ["card"]
