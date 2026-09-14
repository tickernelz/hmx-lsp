from __future__ import annotations

import os
import pathlib

import pytest

from hmx_core.cache import _digest, load, save
from hmx_core.index import build, indexed_files


def _module(root, name="demo"):
    mod = os.path.join(str(root), "hmx", "module", "basic", name)
    for sub in ("views", "models", os.path.join("static", "js"), "security"):
        os.makedirs(os.path.join(mod, sub), exist_ok=True)
    with open(os.path.join(mod, "__hmx__.py"), "w") as fh:
        fh.write('{"name": "demo"}\n')
    with open(os.path.join(mod, "models", "order.py"), "w") as fh:
        fh.write('class Order(models.Model):\n    class Meta:\n        name = "saleorder"\n')
    with open(os.path.join(mod, "views", "v.xml"), "w") as fh:
        fh.write('<hmx><record id="first_view" model="baseuiview"/></hmx>\n')
    with open(os.path.join(mod, "static", "js", "w.js"), "w") as fh:
        fh.write("FieldRegistry.register('firstwidget', 'FirstComp');\n")
    return mod


def test_indexed_files_covers_every_layer_the_index_reads(tmp_path):
    _module(tmp_path)
    suffixes = {os.path.splitext(p)[1] for p in indexed_files(str(tmp_path))}
    assert {".py", ".xml", ".js"} <= suffixes


@pytest.mark.parametrize(
    "rel,body,probe",
    [
        (os.path.join("views", "v.xml"),
         '<hmx><record id="second_view" model="baseuiview"/></hmx>\n',
         "xml"),
        (os.path.join("static", "js", "w.js"),
         "FieldRegistry.register('secondwidget', 'SecondComp');\n",
         "js"),
    ],
)
def test_cache_invalidates_when_a_non_python_layer_changes(tmp_path, rel, body, probe):
    mod = _module(tmp_path)
    root = str(tmp_path)
    paths = indexed_files(root)
    fresh = build(root)
    assert any("first_view" in key for key in fresh.xmlids.entries)
    assert fresh.webx.known_widget("firstwidget")
    save(root, paths, fresh, name=f"test-{probe}")

    assert load(root, indexed_files(root), name=f"test-{probe}") is not None

    with open(os.path.join(mod, rel), "w") as fh:
        fh.write(body)

    assert load(root, indexed_files(root), name=f"test-{probe}") is None


def test_old_cache_format_is_rejected_after_index_shape_changes(tmp_path):
    import pickle

    from hmx_core.cache import path_for

    _module(tmp_path)
    root = str(tmp_path)
    paths = indexed_files(root)
    index = build(root)
    target = path_for(root, "old")
    pathlib.Path(target).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(target).write_bytes(pickle.dumps({
        "format": 3,
        "digest": _digest(root, paths),
        "index": index,
    }))

    assert load(root, paths, name="old") is None
