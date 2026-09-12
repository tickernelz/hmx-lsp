from __future__ import annotations

import subprocess
import sys

MANIFEST = '''{
    "name": "demo",
    "assets": {
        "webx.assets_backend": [
            "static/js/live.js",
            "static/css/ghost.css",
        ],
    },
}
'''

VIEW = '''<hmx><record id="v" model="baseuiview">
<field name="model">saleorder</field>
<field name="arch" type="xml"><form><field name="nosuchfield"/></form></field>
</record></hmx>
'''

MODEL = '''class Order(models.Model):
    class Meta:
        name = "saleorder"
'''


def _repo(tmp_path):
    mod = tmp_path / "hmx" / "module" / "basic" / "demo"
    (mod / "static" / "js").mkdir(parents=True)
    (mod / "views").mkdir(parents=True)
    (mod / "models").mkdir(parents=True)
    (mod / "static" / "js" / "live.js").write_text("const a = 1;\n")
    (mod / "__hmx__.py").write_text(MANIFEST)
    (mod / "views" / "v.xml").write_text(VIEW)
    (mod / "models" / "order.py").write_text(MODEL)
    return tmp_path


def _check(root, *flags):
    return subprocess.run(
        [sys.executable, "-m", "hmx_ls.cli", "check", "--root", str(root), *flags],
        capture_output=True, text=True,
    )


def test_code_gate_fails_on_a_warning_level_code(tmp_path):
    root = _repo(tmp_path)
    got = _check(root, "--layer", "manifest", "--code", "hmx-dead-asset")
    assert got.returncode == 1
    assert "static/css/ghost.css" in got.stdout
    assert "static/js/live.js" not in got.stdout


def test_code_gate_passes_when_the_code_has_no_findings(tmp_path):
    root = _repo(tmp_path)
    got = _check(root, "--layer", "manifest", "--code", "hmx-no-such-code")
    assert got.returncode == 0


def test_code_gate_reports_only_the_requested_code(tmp_path):
    root = _repo(tmp_path)
    got = _check(root, "--code", "hmx-dead-asset")
    assert "hmx-unknown-field" not in got.stdout
    assert "hmx-dead-asset" in got.stdout


def test_layer_selection_bounds_the_scan(tmp_path):
    root = _repo(tmp_path)
    manifest_only = _check(root, "--layer", "manifest")
    assert "[manifest]" in manifest_only.stdout
    assert "nosuchfield" not in manifest_only.stdout

    xml_only = _check(root, "--layer", "xml")
    assert "nosuchfield" in xml_only.stdout
    assert "ghost.css" not in xml_only.stdout


def test_default_run_still_fails_on_errors_only(tmp_path):
    root = _repo(tmp_path)
    xml_only = _check(root, "--layer", "xml")
    assert xml_only.returncode == 1

    manifest_only = _check(root, "--layer", "manifest")
    assert manifest_only.returncode == 0
