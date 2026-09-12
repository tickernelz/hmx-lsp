from __future__ import annotations

import os

from hmx_core.assets import extract_assets_from_manifest, scan_assets

MANIFEST = """{
    "name": "Demo",
    "assets": {
        "webx.assets_backend": [
            "static/css/a.css",
            "static/css/missing.css",
            "static/css/*.css",
            "static/vue/**/*.vue",
            {"static/libs/x.js": {"load_context": {}}},
        ],
        "webx.assets_icons_svg": [
            "static/svg/logo.svg",
        ],
    },
}
"""


def _build(tmp_path) -> str:
    mod = tmp_path / "hmx" / "module" / "basic" / "demo"
    (mod / "static" / "css").mkdir(parents=True)
    (mod / "static" / "vue" / "views" / "fields").mkdir(parents=True)
    (mod / "static" / "svg").mkdir(parents=True)
    (mod / "static" / "svg" / "logo.svg").write_text("<svg/>")
    (mod / "static" / "css" / "a.css").write_text("a{}")
    (mod / "static" / "css" / "b.css").write_text("b{}")
    (mod / "static" / "vue" / "top.vue").write_text("<template></template>")
    (mod / "static" / "vue" / "views" / "fields" / "deep.vue").write_text("<template></template>")
    (mod / "__hmx__.py").write_text(MANIFEST)
    return str(tmp_path)


def _lookup(idx, pattern):
    found = [e for e in idx.by_module["demo"] if e.pattern == pattern]
    assert len(found) == 1
    return found[0]


def test_existing_literal_is_not_dead(tmp_path):
    idx = scan_assets(_build(tmp_path))
    entry = _lookup(idx, "static/css/a.css")
    assert entry.matches == 1
    assert entry not in idx.dead()


def test_missing_literal_is_dead(tmp_path):
    idx = scan_assets(_build(tmp_path))
    entry = _lookup(idx, "static/css/missing.css")
    assert entry.matches == 0
    assert entry in idx.dead()
    assert [e.pattern for e in idx.dead()] == ["static/css/missing.css"]


def test_glob_counts_every_match(tmp_path):
    idx = scan_assets(_build(tmp_path))
    assert _lookup(idx, "static/css/*.css").matches == 2


def test_recursive_glob_reaches_nested_file(tmp_path):
    idx = scan_assets(_build(tmp_path))
    assert _lookup(idx, "static/vue/**/*.vue").matches == 2


def test_bundles_are_discoverable(tmp_path):
    idx = scan_assets(_build(tmp_path))
    assert idx.known_bundle("webx.assets_backend")
    assert idx.known_bundle("webx.assets_icons_svg")
    assert not idx.known_bundle("webx.assets_typo")
    assert not idx.known_bundle("")


def test_entries_carry_manifest_location(tmp_path):
    root = _build(tmp_path)
    rel = os.path.join("hmx", "module", "basic", "demo", "__hmx__.py")
    idx = scan_assets(root)
    assert list(idx.by_file) == [rel]
    entry = _lookup(idx, "static/svg/logo.svg")
    assert entry.bundle == "webx.assets_icons_svg"
    assert entry.module == "demo"
    assert entry.loc.path == rel
    assert entry.loc.line == 12
    assert entry.matches == 1


def test_non_literal_entries_are_skipped(tmp_path):
    root = _build(tmp_path)
    path = os.path.join(root, "hmx", "module", "basic", "demo", "__hmx__.py")
    entries = extract_assets_from_manifest(path, "demo/__hmx__.py", "demo")
    assert [e.pattern for e in entries] == [
        "static/css/a.css",
        "static/css/missing.css",
        "static/css/*.css",
        "static/vue/**/*.vue",
        "static/svg/logo.svg",
    ]
    assert all(e.matches == 0 for e in entries)


def test_missing_module_dir_yields_empty_index(tmp_path):
    idx = scan_assets(str(tmp_path))
    assert idx.bundles == {}
    assert idx.by_file == {}
