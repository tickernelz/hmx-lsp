from __future__ import annotations

import os
from unittest.mock import patch

from hmx_core.index import Index
from hmx_core.locations import Loc
from hmx_core.resolve import Resolver
from hmx_core.xmlids import XmlIdEntry
from hmx_ls.cli import cmd_inspect, cmd_setup, cmd_where_used
from hmx_ls.mcp import (
    _get_server,
    hmx_definition,
    hmx_diagnose,
    hmx_hover,
    hmx_model_info,
    hmx_where_used,
)


def setup_mock_mcp_environment(tmp_path):
    idx = Index()
    emp = idx.entry("hremployee")
    emp.sites.append(Loc("models/hr.py", 10, 0))
    emp.declared["department_id"] = Loc("models/hr.py", 12, 4)
    emp.methods["get_subordinates"] = Loc("models/hr.py", 25, 4)
    idx.xmlids.models["hremployee"] = ["core_hr.view_employee"]
    idx.xmlids.entries["core_hr.view_employee"] = XmlIdEntry(
        xmlid="core_hr.view_employee",
        model="baseuiview",
        name="view.hr.employee",
        loc=Loc("views/hr.xml", 5, 0),
    )

    class Args:
        model = "hremployee"
        field = ""
        root = str(tmp_path)
        target = "claude"

    return idx, Args()


def test_mcp_model_info_and_where_used(tmp_path):
    idx, _ = setup_mock_mcp_environment(tmp_path)

    class MockServer:
        root = str(tmp_path)
        index = idx
        resolver = Resolver(idx)
        workspace = None

    with patch("hmx_ls.mcp._get_server", return_value=MockServer()):
        info = hmx_model_info("hremployee")
        assert info["model"] == "hremployee"
        assert "department_id" in info["composed_fields"]
        assert "get_subordinates" in info["composed_methods"]

        used = hmx_where_used("hremployee")
        assert len(used) >= 1

        used_field = hmx_where_used("hremployee", "department_id")
        assert len(used_field) == 1
        assert used_field[0]["line"] == 12


def test_cli_setup_commands(capsys):
    class SetupArgs:
        target = "vscode"
    ret = cmd_setup(SetupArgs())
    assert ret == 0
    captured = capsys.readouterr()
    assert "hmx.pythonPath" in captured.out

    class OmpArgs:
        target = "omp"
    ret_omp = cmd_setup(OmpArgs())
    assert ret_omp == 0
    captured_omp = capsys.readouterr()
    assert "mcp" in captured_omp.out
