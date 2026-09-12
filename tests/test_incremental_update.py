from __future__ import annotations

import os

from hmx_core.index import build
from hmx_core.styles import StyleIndex, scan_styles


def _repo(tmp_path):
    mod = tmp_path / "hmx" / "module" / "basic" / "demo"
    for sub in ("models", "views", "security", os.path.join("static", "js"),
                os.path.join("static", "vue"), os.path.join("static", "css")):
        (mod / sub).mkdir(parents=True, exist_ok=True)
    (mod / "__hmx__.py").write_text(
        '{"name": "demo", "assets": {"webx.assets_backend": ["static/js/*.js"]}}\n')
    (mod / "models" / "order.py").write_text(
        'class Order(models.Model):\n    class Meta:\n        name = "saleorder"\n')
    (mod / "static" / "js" / "w.js").write_text(
        "FieldRegistry.register('firstwidget', 'FirstComp');\n")
    (mod / "static" / "vue" / "c.vue").write_text("<template/>\n")
    (mod / "security" / "ir.model.access.csv").write_text(
        "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
        "a,a,demo.model_saleorder,base.group_user,1,1,1,1\n")
    return mod


def _save(index, mod, rel_in_module, body):
    target = mod / rel_in_module
    target.write_text(body)
    rel = os.path.relpath(str(target), index.root)
    return index.update_file(rel, body.encode("utf-8"))


def test_js_widget_registration_refreshes_on_save(tmp_path):
    mod = _repo(tmp_path)
    index = build(str(tmp_path))
    assert index.webx.known_widget("firstwidget")

    _save(index, mod, os.path.join("static", "js", "w.js"),
          "FieldRegistry.register('secondwidget', 'SecondComp');\n")

    assert index.webx.known_widget("secondwidget")
    assert not index.webx.known_widget("firstwidget")


def test_js_store_and_template_refresh_on_save(tmp_path):
    mod = _repo(tmp_path)
    _save_body = "defineStore('firststore', {});\n"
    (mod / "static" / "js" / "s.js").write_text(_save_body)
    index = build(str(tmp_path))
    assert index.webx.known_store("firststore")

    _save(index, mod, os.path.join("static", "js", "s.js"),
          "defineStore('secondstore', {});\n")

    assert index.webx.known_store("secondstore")
    assert not index.webx.known_store("firststore")


def test_manifest_asset_bundle_refreshes_on_save(tmp_path):
    mod = _repo(tmp_path)
    index = build(str(tmp_path))
    assert [e.pattern for e in index.assets.dead()] == []

    _save(index, mod, "__hmx__.py",
          '{"name": "demo", "assets": {"webx.assets_backend": ["static/css/ghost.css"]}}\n')

    assert [e.pattern for e in index.assets.dead()] == ["static/css/ghost.css"]


def test_security_csv_refreshes_on_save(tmp_path):
    mod = _repo(tmp_path)
    index = build(str(tmp_path))
    assert index.security.acls_for_group("base.group_user")

    _save(index, mod, os.path.join("security", "ir.model.access.csv"),
          "id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink\n"
          "a,a,demo.model_saleorder,base.group_manager,1,1,1,1\n")

    assert index.security.acls_for_group("base.group_manager")
    assert not index.security.acls_for_group("base.group_user")


def test_vue_component_refreshes_on_save(tmp_path):
    mod = _repo(tmp_path)
    (mod / "static" / "vue" / "c.vue").write_text(
        '<template name="first-card"></template>\n')
    index = build(str(tmp_path))
    assert index.webx.known_component("first-card")

    _save(index, mod, os.path.join("static", "vue", "c.vue"),
          '<template name="second-card"></template>\n')

    assert index.webx.known_component("second-card")
    assert not index.webx.known_component("first-card")


def test_forget_file_is_scoped_to_that_file(tmp_path):
    mod = _repo(tmp_path)
    (mod / "static" / "js" / "other.js").write_text(
        "FieldRegistry.register('keepwidget', 'KeepComp');\n")
    index = build(str(tmp_path))
    assert index.webx.known_widget("keepwidget")

    _save(index, mod, os.path.join("static", "js", "w.js"),
          "FieldRegistry.register('replaced', 'ReplacedComp');\n")

    assert index.webx.known_widget("keepwidget")
    assert index.webx.known_widget("replaced")


def test_style_index_rescans_after_a_stylesheet_changes(tmp_path):
    mod = _repo(tmp_path)
    css = mod / "static" / "css" / "a.css"
    css.write_text(".firstclass { color: red; }\n")
    first = scan_styles(str(tmp_path))
    assert first.declarations("firstclass")

    css.write_text(".secondclass { color: red; }\n")
    stale = first
    assert stale.declarations("firstclass")
    assert not stale.declarations("secondclass")

    fresh = scan_styles(str(tmp_path))
    assert fresh.declarations("secondclass")
    assert not fresh.declarations("firstclass")


def test_server_drops_the_cached_style_index_on_stylesheet_save():
    from hmx_ls.server import HmxLanguageServer

    server = HmxLanguageServer.__new__(HmxLanguageServer)
    server.root = "/tmp/mock_hmx"
    server._styles = StyleIndex()
    assert server.styles is not None

    server._styles = None
    assert isinstance(server.styles, StyleIndex)
