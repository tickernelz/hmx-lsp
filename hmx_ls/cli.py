from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys

from hmx_ls import __version__


def _binary_name() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if system == "windows":
        return "hmx-lsp-windows-arm64.exe" if arm else "hmx-lsp-windows-x64.exe"
    if system == "darwin":
        return "hmx-lsp-darwin-arm64" if arm else "hmx-lsp-darwin-x64"
    return "hmx-lsp-linux-arm64" if arm else "hmx-lsp-linux-x64"


def _launch_spec() -> tuple[str, list[str]]:
    frozen = getattr(sys, "frozen", False)
    if frozen:
        return os.path.abspath(sys.executable), []
    found = shutil.which("hmx-lsp") or shutil.which("hmx-ls")
    if found:
        return found, []
    return sys.executable, ["-m", "hmx_ls.cli"]


def _resolve_root(explicit: str | None) -> str:
    if explicit:
        return os.path.abspath(explicit)
    env = os.environ.get("HMX_ROOT")
    if env:
        return os.path.abspath(env)
    current = os.path.abspath(os.getcwd())
    while True:
        if os.path.isdir(os.path.join(current, "hmx", "module")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.getcwd())
        current = parent


def _load_index(root: str):
    from hmx_core.cache import load, save
    from hmx_core.index import build, python_files
    from hmx_core.resolve import Resolver

    py_paths = python_files(root)
    index = load(root, py_paths)
    if index is None:
        index = build(root)
        save(root, py_paths, index)
    return index, Resolver(index)


class _Bridge:
    def __init__(self, root: str, index, resolver):
        self.root = root
        self.index = index
        self.resolver = resolver
        self.workspace = _NullWorkspace()


class _NullWorkspace:
    def get_text_document(self, uri: str):
        return None


def cmd_serve(args) -> int:
    from hmx_ls.server import main

    main()
    return 0


def cmd_mcp(args) -> int:
    from hmx_ls.mcp import run_mcp

    os.environ["HMX_ROOT"] = _resolve_root(args.root)
    run_mcp()
    return 0


def cmd_check(args) -> int:
    from hmx_ls.features.diagnostics import compute_diagnostics
    from hmx_core.index import xml_files
    from hmx_ls.cursor.common import path_to_uri

    root = _resolve_root(args.root)
    index, resolver = _load_index(root)
    bridge = _Bridge(root, index, resolver)

    paths = xml_files(root)
    errors = 0
    warnings = 0
    for path in paths:
        for diag in compute_diagnostics(bridge, path_to_uri(path)):
            severity = str(diag.severity).lower()
            rel = os.path.relpath(path, root)
            line = diag.range.start.line + 1
            if "error" in severity:
                errors += 1
                print(f"{rel}:{line}: error [{diag.code}] {diag.message}")
            elif not args.errors_only:
                warnings += 1
                print(f"{rel}:{line}: warning [{diag.code}] {diag.message}")

    print(f"\nchecked {len(paths)} XML files | errors {errors} | warnings {warnings}")
    return 1 if errors > 0 else 0


def cmd_inspect(args) -> int:
    root = _resolve_root(args.root)
    index, resolver = _load_index(root)
    norm = args.model.split(".")[-1].lower().replace("_", "")
    if not resolver.known(norm):
        print(f"error: unknown model '{args.model}'", file=sys.stderr)
        return 1

    entry = index.models.get(norm)
    fields = resolver.fields(norm)
    methods = resolver.methods(norm)

    if args.json:
        print(json.dumps({
            "model": norm,
            "sites": [str(loc) for loc in (entry.sites if entry else [])],
            "inherits": sorted(entry.edges if entry else []),
            "fields": {name: str(loc) for name, loc in sorted(fields.items())},
            "methods": {name: str(loc) for name, loc in sorted(methods.items())},
        }, indent=2))
        return 0

    print(f"model: {norm}")
    print(f"declaration sites ({len(entry.sites) if entry else 0}):")
    for loc in (entry.sites if entry else []):
        print(f"  {loc}")
    print(f"inherits: {', '.join(sorted(entry.edges)) if entry and entry.edges else '-'}")
    print(f"fields ({len(fields)}):")
    for name in sorted(fields):
        target = resolver.comodel(norm, name)
        print(f"  {name}{' -> ' + target if target else ''}")
    print(f"methods ({len(methods)}):")
    for name in sorted(methods):
        print(f"  {name}()")
    return 0


def cmd_where_used(args) -> int:
    root = _resolve_root(args.root)
    index, resolver = _load_index(root)
    norm = args.model.split(".")[-1].lower().replace("_", "")
    if not resolver.known(norm):
        print(f"error: unknown model '{args.model}'", file=sys.stderr)
        return 1

    if args.field:
        loc = resolver.fields(norm).get(args.field)
        if loc is None:
            print(f"field '{args.field}' not found on '{norm}'", file=sys.stderr)
            return 1
        print(f"{args.field} declared at {loc}")
        return 0

    entry = index.models.get(norm)
    if entry:
        print(f"python classes ({len(entry.sites)}):")
        for loc in entry.sites:
            print(f"  {loc}")
    xmlids = index.xmlids.models.get(norm, [])
    if xmlids:
        print(f"xml records ({len(xmlids)}):")
        for xid in xmlids:
            found = index.xmlids.entries.get(xid)
            if found:
                print(f"  {xid} ({found.loc})")
    acls = index.security.acls_for_model(norm)
    if acls:
        print(f"security acls ({len(acls)}):")
        for acl in acls:
            print(f"  {acl.name} ({acl.loc})")
    return 0


def cmd_doctor(args) -> int:
    command, prefix = _launch_spec()
    root = _resolve_root(args.root)
    print(f"hmx-lsp {__version__}")
    print(f"python           {sys.version.split()[0]} ({sys.executable})")
    print(f"platform         {platform.system()} {platform.machine()}")
    print(f"frozen binary    {bool(getattr(sys, 'frozen', False))}")
    print(f"expected asset   {_binary_name()}")
    print(f"launch command   {command} {' '.join(prefix)}".rstrip())
    print(f"HMX_LSP_PATH     {os.environ.get('HMX_LSP_PATH') or '-'}")
    print(f"HMX_ROOT         {os.environ.get('HMX_ROOT') or '-'}")
    print(f"resolved root    {root}")
    print(f"root is hmx repo {os.path.isdir(os.path.join(root, 'hmx', 'module'))}")
    print(f"on PATH          {shutil.which('hmx-lsp') or shutil.which('hmx-ls') or '-'}")

    missing = []
    for module in ("pygls", "lsprotocol", "lxml", "mcp"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    print(f"dependencies     {'ok' if not missing else 'missing ' + ', '.join(missing)}")
    return 1 if missing else 0


def cmd_setup(args) -> int:
    command, prefix = _launch_spec()
    target = args.target

    def argv(*extra: str) -> list[str]:
        return [*prefix, *extra]

    if target == "vscode":
        print("// .vscode/settings.json")
        print(json.dumps({
            "hmx.server.path": command if not prefix else "",
            "hmx.server.autoDownload": True,
            "hmx.server.version": "latest",
        }, indent=2))
        print("\n// Leave hmx.server.path empty to auto-resolve via HMX_LSP_PATH, PATH, or GitHub release.")
    elif target == "zed":
        print("// .zed/settings.json")
        print(json.dumps({
            "lsp": {"hmx-ls": {"binary": {"path": command, "arguments": argv("serve")}}},
            "languages": {
                "XML": {"language_servers": ["hmx-ls"]},
                "Python": {"language_servers": ["pyright", "hmx-ls"]},
                "JavaScript": {"language_servers": ["vtsls", "hmx-ls"]},
                "Vue.js": {"language_servers": ["vue-language-server", "hmx-ls"]},
            },
        }, indent=2))
    elif target == "jetbrains":
        print("# Help -> Edit Custom VM Options, then restart the IDE:")
        print(f"-Dhmx.lsp.path={command}")
        print("\n# Or export before launching the IDE:")
        print(f"export HMX_LSP_PATH={command}")
    elif target == "omp":
        print("# .omp/agent/config.yml")
        print("mcp:")
        print("  servers:")
        print("    hmx:")
        print(f"      command: {command}")
        print("      args:")
        for item in argv("mcp"):
            print(f"        - {item}")
    elif target in ("claude", "codex"):
        key = "mcpServers" if target == "claude" else "mcp_servers"
        print(f"// {'.mcp.json' if target == 'claude' else 'mcp_servers.json'}")
        print(json.dumps({key: {"hmx-lsp": {"command": command, "args": argv("mcp")}}}, indent=2))
    elif target == "env":
        print(f"export HMX_LSP_PATH={command}")
        print(f"export HMX_ROOT={_resolve_root(None)}")
    else:
        print(f"unknown target '{target}'", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hmx-lsp", description="HMX cross-layer language server")
    parser.add_argument("--version", action="version", version=f"hmx-lsp {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="run the LSP server over stdio")

    p_mcp = sub.add_parser("mcp", help="run the MCP server for AI assistants")
    p_mcp.add_argument("--root", help="HMX repository root")

    p_check = sub.add_parser("check", help="run cross-layer validation over the workspace")
    p_check.add_argument("--root", help="HMX repository root")
    p_check.add_argument("--errors-only", action="store_true", help="suppress warnings")

    p_inspect = sub.add_parser("inspect", help="show composed fields, methods, and inheritance")
    p_inspect.add_argument("model")
    p_inspect.add_argument("--root", help="HMX repository root")
    p_inspect.add_argument("--json", action="store_true", help="emit JSON")

    p_where = sub.add_parser("where-used", help="find usages across Python, XML, and security CSV")
    p_where.add_argument("model")
    p_where.add_argument("field", nargs="?", default="")
    p_where.add_argument("--root", help="HMX repository root")

    p_doctor = sub.add_parser("doctor", help="report interpreter, platform, and dependency state")
    p_doctor.add_argument("--root", help="HMX repository root")

    p_setup = sub.add_parser("setup", help="print an editor or AI assistant configuration snippet")
    p_setup.add_argument(
        "target",
        choices=["vscode", "zed", "jetbrains", "omp", "claude", "codex", "env"],
    )

    return parser


def main() -> None:
    args = build_parser().parse_args()
    dispatch = {
        "serve": cmd_serve,
        "mcp": cmd_mcp,
        "check": cmd_check,
        "inspect": cmd_inspect,
        "where-used": cmd_where_used,
        "doctor": cmd_doctor,
        "setup": cmd_setup,
    }
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
