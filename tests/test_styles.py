from __future__ import annotations

import os

from hmx_core.styles import (
    StyleIndex,
    extract_styles,
    extract_styles_from_file,
    scan_styles,
)


def _names(content: str) -> list[str]:
    return [e.name for e in extract_styles(content, "static/css/a.css")]


def _module_file(tmp_path, rel: str, content: str) -> str:
    path = tmp_path / "hmx" / "module" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_simple_class_is_declared():
    assert _names(".foo { color: red; }") == ["foo"]


def test_compound_selector_declares_both_tokens():
    assert _names(".a.b { color: red; }") == ["a", "b"]


def test_descendant_selector_declares_both_tokens():
    assert _names(".a .b { color: red; }") == ["a", "b"]


def test_child_combinator_declares_both_tokens():
    assert _names(".a > .b { color: red; }") == ["a", "b"]


def test_pseudo_class_declares_only_the_class():
    assert _names(".a:hover { color: red; }") == ["a"]


def test_pseudo_element_declares_only_the_class():
    assert _names(".a::before { content: 'x'; }") == ["a"]


def test_attribute_selector_declares_only_the_class():
    assert _names(".a[disabled] { color: red; }") == ["a"]


def test_decimal_values_never_become_classes():
    names = _names(".card { margin: 1.5rem; padding: 0.25em; }")
    assert names == ["card"]
    assert "5rem" not in names
    assert "25em" not in names


def test_decimal_in_at_rule_prelude_is_not_a_class():
    names = _names("@media (min-width: 1.5em) { .wide { color: red; } }")
    assert names == ["wide"]


def test_element_qualified_selector_is_declared():
    assert _names("div.card { color: red; }") == ["card"]


def test_block_comment_declarations_are_ignored():
    assert _names("/* .ghost { color: red; } */\n.real { color: red; }") == ["real"]


def test_line_comment_declarations_are_ignored():
    assert _names("// .ghost { color: red; }\n.real { color: red; }") == ["real"]


def test_string_literal_is_not_a_selector():
    content = ".real { content: '.ghost'; background: url(\"a.ghost2\"); }"
    assert _names(content) == ["real"]


def test_url_path_is_not_a_class():
    names = _names(".real { background: url(../img/logo.png); }")
    assert names == ["real"]
    assert "png" not in names


def test_scss_ampersand_class_is_declared():
    names = _names(".btn { &.active { color: red; } }")
    assert names == ["btn", "active"]


def test_scss_ampersand_suffix_is_skipped():
    assert _names(".btn { &-primary { color: red; } }") == ["btn"]


def test_nested_scss_declares_inner_class():
    assert _names(".outer { .inner { color: red; } }") == ["outer", "inner"]


def test_location_is_one_based_line_and_zero_based_column():
    entries = extract_styles("body { color: red; }\n  .foo { color: red; }", "a.css")
    assert len(entries) == 1
    loc = entries[0].loc
    assert loc.path == "a.css"
    assert loc.line == 2
    assert loc.col == 3
    assert loc.end_col == 6


def test_extract_from_file_reads_disk(tmp_path):
    path = tmp_path / "b.scss"
    path.write_text(".written { color: red; }", encoding="utf-8")
    entries = extract_styles_from_file(str(path), "static/scss/b.scss")
    assert [e.name for e in entries] == ["written"]
    assert entries[0].loc.path == "static/scss/b.scss"


def test_extract_from_missing_file_returns_empty():
    assert extract_styles_from_file("/nonexistent/x.css", "x.css") == []


def test_scan_collects_class_from_two_files(tmp_path):
    _module_file(tmp_path, "basic/mod_a/static/css/a.css", ".shared { color: red; }")
    _module_file(tmp_path, "basic/mod_b/static/scss/b.scss", "\n.shared { color: blue; }")
    idx = scan_styles(str(tmp_path))
    entries = idx.declarations("shared")
    assert len(entries) == 2
    paths = sorted(e.loc.path for e in entries)
    assert paths == [
        os.path.join("hmx", "module", "basic", "mod_a", "static", "css", "a.css"),
        os.path.join("hmx", "module", "basic", "mod_b", "static", "scss", "b.scss"),
    ]
    assert len({e.loc.path for e in entries}) == 2
    assert sorted(e.loc.line for e in entries) == [1, 2]


def test_scan_records_by_file_names(tmp_path):
    rel = "basic/mod_a/static/css/a.css"
    _module_file(tmp_path, rel, ".one { color: red; }\n.two.one { color: red; }")
    idx = scan_styles(str(tmp_path))
    key = os.path.join("hmx", "module", "basic", "mod_a", "static", "css", "a.css")
    assert idx.by_file[key] == ["one", "two"]


def test_scan_skips_vendored_dirs(tmp_path):
    _module_file(tmp_path, "basic/mod_a/node_modules/pkg/x.css", ".vendored { color: red; }")
    _module_file(tmp_path, "basic/mod_a/static/css/a.css", ".owned { color: red; }")
    idx = scan_styles(str(tmp_path))
    assert idx.declarations("vendored") == []
    assert len(idx.declarations("owned")) == 1


def test_scan_without_module_dir_is_empty(tmp_path):
    idx = scan_styles(str(tmp_path))
    assert idx.classes == {}
    assert idx.by_file == {}


def test_declarations_of_unknown_name_is_empty():
    idx = StyleIndex()
    assert idx.declarations("nope") == []
    assert idx.declarations("") == []


def test_prefixed_filters_sorts_and_limits(tmp_path):
    content = ".card {}\n.cart {}\n.cable {}\n.deck {}"
    _module_file(tmp_path, "basic/mod_a/static/css/a.css", content)
    idx = scan_styles(str(tmp_path))
    assert idx.prefixed("ca") == ["cable", "card", "cart"]
    assert idx.prefixed("ca", limit=2) == ["cable", "card"]
    assert idx.prefixed("zz") == []
    assert idx.prefixed("ca", limit=0) == []
