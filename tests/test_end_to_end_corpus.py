from __future__ import annotations

import os
import shutil

import pytest

from hmx_core.cache import load, save
from hmx_core.index import build, indexed_files
from hmx_core.resolve import Resolver
from hmx_core.styles import scan_styles
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.features.diagnostics import compute_diagnostics

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "corpus")
MODULE = os.path.join("hmx", "module", "basic", "demo")


class NullWorkspace:
    def get_text_document(self, uri):
        return None


class Bridge:
    def __init__(self, root, index):
        self.root = root
        self.index = index
        self.resolver = Resolver(index)
        self.workspace = NullWorkspace()


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    shutil.copytree(FIXTURE, root)
    return str(root)


def _diags(root, index, rel):
    return compute_diagnostics(Bridge(root, index), path_to_uri(os.path.join(root, rel)))


def test_index_sees_every_layer(corpus):
    index = build(corpus)
    assert set(index.models) >= {"saleorder", "basepartner"}
    assert index.xmlids.entries
    assert index.webx.known_widget("demowidget")
    assert index.webx.known_store("demostore")
    assert index.webx.known_component("demo-card")
    assert index.security.by_file
    assert index.assets.known_bundle("webx.assets_backend")
    assert scan_styles(corpus).declarations("demo-card")


def test_indexed_files_covers_all_six_suffixes(corpus):
    suffixes = {os.path.splitext(p)[1] for p in indexed_files(corpus)}
    assert {".py", ".xml", ".js", ".vue", ".csv", ".css"} <= suffixes


def test_each_layer_reports_its_own_defect(corpus):
    index = build(corpus)

    xml = [d.code for d in _diags(corpus, index, os.path.join(MODULE, "views", "order.xml"))]
    assert "hmx-unknown-field" in xml

    manifest = [d.code for d in _diags(corpus, index, os.path.join(MODULE, "__hmx__.py"))]
    assert manifest == ["hmx-dead-asset"]

    csv = [d.code for d in _diags(corpus, index,
                                  os.path.join(MODULE, "security", "ir.model.access.csv"))]
    assert "hmx-unknown-model" in csv


def test_known_good_references_are_silent(corpus):
    index = build(corpus)
    messages = [d.message for d in
                _diags(corpus, index, os.path.join(MODULE, "views", "order.xml"))]
    assert not [m for m in messages if "'partner'" in m]
    assert not [m for m in messages if "'amount'" in m]
    assert not [m for m in messages if "action_confirm" in m]
    assert not [m for m in messages if "demowidget" in m]
    assert [m for m in messages if "ghostfield" in m]


@pytest.mark.parametrize("rel,body", [
    (os.path.join(MODULE, "views", "order.xml"),
     '<hmx><record id="changed_view" model="baseuiview"/></hmx>\n'),
    (os.path.join(MODULE, "static", "js", "widget.js"),
     'FieldRegistry.register("changedwidget", "ChangedComp");\n'),
    (os.path.join(MODULE, "static", "vue", "card.vue"),
     '<template name="changed-card"></template>\n'),
    (os.path.join(MODULE, "static", "css", "style.css"), ".changed {}\n"),
    (os.path.join(MODULE, "security", "ir.model.access.csv"),
     "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"),
    (os.path.join(MODULE, "models", "order.py"), "CHANGED = 1\n"),
])
def test_cache_invalidates_for_every_layer(corpus, rel, body):
    paths = indexed_files(corpus)
    save(corpus, paths, build(corpus), name="e2e")
    assert load(corpus, indexed_files(corpus), name="e2e") is not None

    with open(os.path.join(corpus, rel), "w") as fh:
        fh.write(body)

    assert load(corpus, indexed_files(corpus), name="e2e") is None


def test_saving_a_widget_file_refreshes_the_index_without_a_rebuild(corpus):
    index = build(corpus)
    rel = os.path.join(MODULE, "static", "js", "widget.js")
    body = 'FieldRegistry.register("renamedwidget", "RenamedComp");\n'
    with open(os.path.join(corpus, rel), "w") as fh:
        fh.write(body)

    index.update_file(rel, body.encode("utf-8"))

    assert index.webx.known_widget("renamedwidget")
    assert not index.webx.known_widget("demowidget")


def test_saving_the_manifest_refreshes_dead_asset_findings(corpus):
    index = build(corpus)
    assert [e.pattern for e in index.assets.dead()] == ["static/js/missing/*.js"]

    rel = os.path.join(MODULE, "__hmx__.py")
    body = '{"name": "demo", "assets": {"webx.assets_backend": ["static/js/widget.js"]}}\n'
    with open(os.path.join(corpus, rel), "w") as fh:
        fh.write(body)

    index.update_file(rel, body.encode("utf-8"))

    assert index.assets.dead() == []
