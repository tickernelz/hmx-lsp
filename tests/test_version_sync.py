from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "bump_version.py"

PYPROJECT = """[build-system]
requires = ["setuptools>=61.0"]

[project]
name = "fake"
version = "{v}"

[tool.fake]
version = "9.9.9"
"""

INIT = """from __future__ import annotations

__version__ = "{v}"
"""

GRADLE_PROPERTIES = """pluginVersion={v}
platformVersion=2024.2
"""

GRADLE_KTS = """version = providers.gradleProperty("pluginVersion").getOrElse("{v}")

intellijPlatform {{
    pycharmProfessional(providers.gradleProperty("platformVersion").getOrElse("2024.2"))
}}
"""

EXTENSION_TOML = """id = "fake"
version = "{v}"

[language_servers.fake]
name = "fake"
version = "9.9.9"
"""

CARGO_TOML = """[package]
name = "fake"
version = "{v}"
edition = "2021"

[dependencies]
zed_extension_api = "0.7.0"

[dependencies.serde]
version = "1.2.3"
features = ["derive"]
"""

PACKAGE_JSON = """{{
  "name": "fake",
  "version": "{v}",
  "dependencies": {{
    "vscode-languageclient": "9.0.1"
  }},
  "contributes": {{
    "version": "9.9.9"
  }}
}}
"""

LAYOUT = {
    "pyproject.toml": PYPROJECT,
    "hmx_ls/__init__.py": INIT,
    "editors/jetbrains/gradle.properties": GRADLE_PROPERTIES,
    "editors/jetbrains/build.gradle.kts": GRADLE_KTS,
    "editors/zed/extension.toml": EXTENSION_TOML,
    "editors/zed/Cargo.toml": CARGO_TOML,
    "editors/vscode/package.json": PACKAGE_JSON,
}


def _tree(tmp_path, version="0.1.0"):
    for relative, template in LAYOUT.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.format(v=version))
    return tmp_path


def _run(root, *flags):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *flags],
        capture_output=True, text=True,
    )


def test_check_passes_when_every_declaration_agrees(tmp_path):
    got = _run(_tree(tmp_path), "--check")
    assert got.returncode == 0, got.stdout
    reported = [line.split() for line in got.stdout.splitlines() if not line.startswith("ok:")]
    assert [columns[0] for columns in reported] == list(LAYOUT)
    assert {columns[1] for columns in reported} == {"0.1.0"}
    assert "ok: 7 declarations agree on 0.1.0" in got.stdout


def test_check_fails_and_names_the_drifting_file(tmp_path):
    root = _tree(tmp_path)
    drifted = root / "editors/vscode/package.json"
    drifted.write_text(PACKAGE_JSON.format(v="0.4.2"))

    got = _run(root, "--check")
    assert got.returncode == 1
    reported = dict(
        (line.split()[0], line) for line in got.stdout.splitlines() if line.startswith(("pyproject", "editors"))
    )
    assert "0.4.2" in reported["editors/vscode/package.json"]
    assert "MISMATCH" in reported["editors/vscode/package.json"]
    assert "MISMATCH" not in reported["pyproject.toml"]
    assert "drift: 1 of 7 declarations disagree" in got.stdout
    assert got.stdout.rstrip().endswith("  editors/vscode/package.json")


def test_check_expect_rejects_a_version_that_is_not_the_release_tag(tmp_path):
    root = _tree(tmp_path)
    assert _run(root, "--check", "--expect", "0.1.0").returncode == 0

    got = _run(root, "--check", "--expect", "0.2.0")
    assert got.returncode == 1
    assert "agree on 0.1.0 but 0.2.0 was expected" in got.stdout


def test_bump_rewrites_all_seven_declarations(tmp_path):
    root = _tree(tmp_path)
    got = _run(root, "0.3.0")
    assert got.returncode == 0, got.stdout
    assert "7 of 7 declarations rewritten to 0.3.0" in got.stdout

    for relative in LAYOUT:
        assert "0.3.0" in (root / relative).read_text(), relative
    assert _run(root, "--check", "--expect", "0.3.0").returncode == 0


def test_bump_leaves_unrelated_version_literals_alone(tmp_path):
    root = _tree(tmp_path)
    assert _run(root, "0.3.0").returncode == 0

    assert (root / "editors/jetbrains/gradle.properties").read_text() == (
        "pluginVersion=0.3.0\nplatformVersion=2024.2\n"
    )
    assert 'getOrElse("2024.2")' in (root / "editors/jetbrains/build.gradle.kts").read_text()
    assert '"version": "9.9.9"' in (root / "editors/vscode/package.json").read_text()
    assert (root / "editors/zed/extension.toml").read_text().endswith('version = "9.9.9"\n')
    assert (root / "pyproject.toml").read_text().endswith('version = "9.9.9"\n')


def test_bump_never_touches_a_cargo_dependency_version(tmp_path):
    root = _tree(tmp_path)
    assert _run(root, "0.3.0").returncode == 0

    cargo = (root / "editors/zed/Cargo.toml").read_text()
    assert cargo == CARGO_TOML.format(v="0.3.0")
    assert 'version = "1.2.3"' in cargo
    assert cargo.count('version = "0.3.0"') == 1
    assert 'zed_extension_api = "0.7.0"' in cargo


def test_missing_declaration_is_reported_against_its_own_file(tmp_path):
    root = _tree(tmp_path)
    (root / "editors/zed/Cargo.toml").write_text("[package]\nname = \"fake\"\n")

    got = _run(root, "--check")
    assert got.returncode == 1
    assert "error: editors/zed/Cargo.toml: no version key at [package]" in got.stdout
