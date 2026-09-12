from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAUNCH_TARGETS = ["zed", "jetbrains", "omp", "claude", "codex", "env"]


def _setup(target: str) -> str:
    got = subprocess.run(
        [sys.executable, "-m", "hmx_ls.cli", "setup", target],
        cwd=REPO, env={**os.environ, "PYTHONPATH": REPO},
        capture_output=True, text=True, check=True,
    )
    return got.stdout


def _launch_command(target: str, text: str) -> list[str]:
    if target == "zed":
        binary = json.loads(text[text.index("{"):])["lsp"]["hmx-ls"]["binary"]
        return [binary["path"], *binary["arguments"]]
    if target in ("claude", "codex"):
        key = "mcpServers" if target == "claude" else "mcp_servers"
        entry = json.loads(text[text.index("{"):])[key]["hmx-lsp"]
        return [entry["command"], *entry["args"]]
    if target == "omp":
        command = re.search(r"command:\s*(\S+)", text).group(1)
        return [command, *re.findall(r"^\s+- (\S+)$", text, re.M)]
    return [re.search(r"HMX_LSP_PATH=(\S+)", text).group(1)]


@pytest.mark.parametrize("target", LAUNCH_TARGETS)
def test_setup_emits_an_executable_launcher(target):
    argv = _launch_command(target, _setup(target))
    assert os.path.isabs(argv[0])
    assert os.access(argv[0], os.X_OK)


@pytest.mark.parametrize("target", LAUNCH_TARGETS)
def test_setup_launcher_runs_from_an_unrelated_directory(tmp_path, target):
    argv = _launch_command(target, _setup(target))
    probe = [a for a in argv if a not in ("serve", "mcp")] + ["--version"]
    got = subprocess.run(probe, cwd=str(tmp_path), capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    assert "hmx-lsp" in got.stdout


def test_launch_spec_prefers_a_launcher_that_carries_its_own_pythonpath():
    from hmx_ls.cli import _launch_spec

    command, prefix = _launch_spec()
    if prefix:
        pytest.skip("no installed entry point or wrapper on this machine")
    assert os.access(command, os.X_OK)


def test_every_mcp_tool_carries_a_description():
    from hmx_ls.mcp import TOOL_DESCRIPTIONS

    expected = {"hmx_definition", "hmx_hover", "hmx_model_info",
                "hmx_where_used", "hmx_diagnose"}
    assert set(TOOL_DESCRIPTIONS) == expected
    for name, description in TOOL_DESCRIPTIONS.items():
        assert len(description) >= 120, name


def test_mcp_registration_uses_the_description_table():
    from hmx_ls import mcp as mcp_module

    if mcp_module.mcp is None:
        pytest.skip("fastmcp not installed")
    tools = mcp_module.mcp._tool_manager.list_tools()
    by_name = {t.name: t for t in tools}
    assert set(by_name) == set(mcp_module.TOOL_DESCRIPTIONS)
    for name, tool in by_name.items():
        assert tool.description == mcp_module.TOOL_DESCRIPTIONS[name]
