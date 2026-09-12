from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_core.xmlids import XmlIdEntry
from hmx_ls import __version__
from hmx_ls.cli import (
    _binary_name,
    _launch_spec,
    _resolve_root,
    build_parser,
    cmd_doctor,
    cmd_inspect,
    cmd_setup,
    cmd_where_used,
)
from hmx_ls.mcp import hmx_model_info, hmx_where_used


class _Args:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def _index_with_model() -> Index:
    idx = Index()
    emp = idx.entry("hremployee")
    emp.sites.append(Loc("models/hr.py", 10, 0))
    emp.declared["department_id"] = Loc("models/hr.py", 12, 4)
    emp.comodel["department_id"] = "hrdepartment"
    emp.methods["get_subordinates"] = Loc("models/hr.py", 25, 4)
    idx.xmlids.models["hremployee"] = ["core_hr.view_employee"]
    idx.xmlids.entries["core_hr.view_employee"] = XmlIdEntry(
        xmlid="core_hr.view_employee",
        model="baseuiview",
        name="view.hr.employee",
        loc=Loc("views/hr.xml", 5, 0),
    )
    return idx


def test_parser_exposes_every_command():
    parser = build_parser()
    sub = next(a for a in parser._actions if getattr(a, "choices", None) and "serve" in a.choices)
    assert set(sub.choices) == {
        "serve", "mcp", "check", "inspect", "where-used", "doctor", "setup",
    }


def test_version_flag_reports_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_binary_name_matches_release_asset_naming():
    name = _binary_name()
    assert name.startswith("hmx-lsp-")
    assert any(name.endswith(suffix) for suffix in ("-x64", "-arm64", "-x64.exe", "-arm64.exe"))


def test_launch_spec_is_derived_from_the_running_interpreter():
    command, prefix = _launch_spec()
    assert command
    assert os.path.isabs(command)
    assert prefix == [] or prefix == ["-m", "hmx_ls.cli"]


def test_resolve_root_prefers_explicit_then_env_then_walk(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    assert _resolve_root(str(explicit)) == str(explicit)

    env_root = tmp_path / "from_env"
    env_root.mkdir()
    monkeypatch.setenv("HMX_ROOT", str(env_root))
    assert _resolve_root(None) == str(env_root)

    monkeypatch.delenv("HMX_ROOT")
    repo = tmp_path / "repo"
    (repo / "hmx" / "module").mkdir(parents=True)
    nested = repo / "hmx" / "module" / "basic" / "core_hr"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert _resolve_root(None) == str(repo)


@pytest.mark.parametrize(
    "target,needle",
    [
        ("vscode", "hmx.server.path"),
        ("zed", "hmx-ls"),
        ("jetbrains", "HMX_LSP_PATH"),
        ("omp", "mcp"),
        ("claude", "mcpServers"),
        ("codex", "mcp_servers"),
        ("env", "HMX_LSP_PATH"),
    ],
)
def test_setup_emits_snippet_per_target(capsys, target, needle):
    assert cmd_setup(_Args(target=target)) == 0
    assert needle in capsys.readouterr().out


def test_setup_rejects_unknown_target(capsys):
    assert cmd_setup(_Args(target="emacs")) == 1
    assert "unknown target" in capsys.readouterr().err


def test_setup_snippets_are_valid_json(capsys):
    for target in ("vscode", "zed", "claude", "codex"):
        cmd_setup(_Args(target=target))
        out = capsys.readouterr().out
        start = out.index("{")
        end = out.rindex("}") + 1
        json.loads(out[start:end])


def test_doctor_reports_environment_and_succeeds(capsys, tmp_path):
    assert cmd_doctor(_Args(root=str(tmp_path))) == 0
    out = capsys.readouterr().out
    for label in ("expected asset", "launch command", "resolved root", "dependencies"):
        assert label in out
    assert __version__ in out


def test_inspect_json_reports_composed_surface(capsys, tmp_path):
    idx = _index_with_model()
    with patch("hmx_ls.cli._load_index", return_value=(idx, Resolver(idx))):
        assert cmd_inspect(_Args(model="hremployee", root=str(tmp_path), json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["model"] == "hremployee"
    assert "department_id" in payload["fields"]
    assert "get_subordinates" in payload["methods"]


def test_inspect_rejects_unknown_model(capsys, tmp_path):
    idx = Index()
    with patch("hmx_ls.cli._load_index", return_value=(idx, Resolver(idx))):
        assert cmd_inspect(_Args(model="nope", root=str(tmp_path), json=False)) == 1
    assert "unknown model" in capsys.readouterr().err


def test_where_used_spans_python_xml_and_field(capsys, tmp_path):
    idx = _index_with_model()
    with patch("hmx_ls.cli._load_index", return_value=(idx, Resolver(idx))):
        assert cmd_where_used(_Args(model="hremployee", field="", root=str(tmp_path))) == 0
        out = capsys.readouterr().out
        assert "models/hr.py" in out
        assert "core_hr.view_employee" in out

        assert cmd_where_used(_Args(model="hremployee", field="department_id", root=str(tmp_path))) == 0
        assert "models/hr.py:12" in capsys.readouterr().out


def test_mcp_model_info_and_where_used(tmp_path):
    idx = _index_with_model()

    class Bridge:
        root = str(tmp_path)
        index = idx
        resolver = Resolver(idx)
        workspace = None

    with patch("hmx_ls.mcp._get_server", return_value=Bridge()):
        info = hmx_model_info("hremployee")
        assert info["model"] == "hremployee"
        assert "department_id" in info["composed_fields"]
        assert "get_subordinates" in info["composed_methods"]

        assert len(hmx_where_used("hremployee")) >= 2
        field_hits = hmx_where_used("hremployee", "department_id")
        assert len(field_hits) == 1
        assert field_hits[0]["line"] == 12
