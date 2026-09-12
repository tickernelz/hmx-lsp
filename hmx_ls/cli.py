from __future__ import annotations

import argparse
import json
import os
import sys

from hmx_core.cache import load, save
from hmx_core.index import build, python_files, xml_files
from hmx_core.resolve import Resolver
from hmx_ls.features.diagnostics import compute_diagnostics


def cmd_serve(args) -> int:
    from hmx_ls.server import main
    main()
    return 0


def cmd_mcp(args) -> int:
    from hmx_ls.mcp import run_mcp
    if args.root:
        os.environ["HMX_ROOT"] = os.path.abspath(args.root)
    run_mcp()
    return 0


def cmd_check(args) -> int:
    root = os.path.abspath(args.root or os.getcwd())
    py_paths = python_files(root)
    index = load(root, py_paths)
    if index is None:
        index = build(root)
        save(root, py_paths, index)
    resolver = Resolver(index)

    class MockWorkspace:
        def get_text_document(self, uri):
            return None

    class ServerBridge:
        def __init__(self, r, idx, res):
            self.root = r
            self.index = idx
            self.resolver = res
            self.workspace = MockWorkspace()

    s = ServerBridge(root, index, resolver)
    xpaths = xml_files(root)
    total_errors = 0

    for p in xpaths:
        uri = f"file://{p}"
        diags = compute_diagnostics(s, uri)
        for d in diags:
            if "error" in str(d.severity).lower():
                total_errors += 1
                rel = os.path.relpath(p, root)
                print(f"{rel}:{d.range.start.line + 1}: [{d.code}] {d.message}")

    print(f"\nCheck completed across {len(xpaths)} XML files. Total errors: {total_errors}")
    return 1 if total_errors > 0 else 0


def cmd_inspect(args) -> int:
    root = os.path.abspath(args.root or os.getcwd())
    py_paths = python_files(root)
    index = load(root, py_paths)
    if index is None:
        index = build(root)
        save(root, py_paths, index)
    resolver = Resolver(index)

    norm = args.model.lower().replace(".", "").replace("_", "")
    if not resolver.known(norm):
        print(f"Error: Unknown model '{args.model}'")
        return 1

    entry = index.models.get(norm)
    fields = resolver.fields(norm)
    methods = resolver.methods(norm)

    print(f"=== Model: {norm} ===")
    print(f"Declaration sites: {[str(loc) for loc in (entry.sites if entry else [])]}")
    print(f"Inheritance edges: {sorted(entry.edges if entry else [])}")
    print(f"Composed fields ({len(fields)}):")
    for f in sorted(fields.keys()):
        cm = resolver.comodel(norm, f)
        target = f" -> {cm}" if cm else ""
        print(f"  - {f}{target}")
    print(f"Composed methods ({len(methods)}):")
    for m in sorted(methods.keys()):
        print(f"  - {m}()")
    return 0


def cmd_where_used(args) -> int:
    root = os.path.abspath(args.root or os.getcwd())
    py_paths = python_files(root)
    index = load(root, py_paths)
    if index is None:
        index = build(root)
        save(root, py_paths, index)
    resolver = Resolver(index)

    norm = args.model.lower().replace(".", "").replace("_", "")
    if not resolver.known(norm):
        print(f"Error: Unknown model '{args.model}'")
        return 1

    if args.field:
        fields = resolver.fields(norm)
        loc = fields.get(args.field)
        if loc:
            print(f"Field '{args.field}' declared at: {loc}")
        else:
            print(f"Field '{args.field}' not found on model '{norm}'")
    else:
        entry = index.models.get(norm)
        if entry:
            print(f"Python classes for '{norm}':")
            for loc in entry.sites:
                print(f"  {loc}")
        xids = index.xmlids.models.get(norm, [])
        if xids:
            print(f"XML view records for '{norm}':")
            for xid in xids:
                xe = index.xmlids.entries.get(xid)
                if xe:
                    print(f"  {xid} ({xe.loc})")
        acls = index.security.acls_for_model(norm)
        if acls:
            print(f"Security ACLs for '{norm}':")
            for acl in acls:
                print(f"  {acl.name} ({acl.loc})")
    return 0


def cmd_setup(args) -> int:
    target = args.target.lower()
    py_bin = sys.executable

    if target == "vscode":
        config = {
            "hmx.pythonPath": py_bin,
            "hmx.serverModule": "hmx_ls.server",
            "hmx.trace.server": "off",
        }
        print("// Put this in .vscode/settings.json:")
        print(json.dumps(config, indent=2))
    elif target == "zed":
        config = {
            "lsp": {
                "hmx-ls": {
                    "binary": {
                        "path": py_bin,
                        "arguments": ["-m", "hmx_ls.server"],
                    }
                }
            },
            "languages": {
                "XML": {"language_servers": ["hmx-ls"]},
                "Python": {"language_servers": ["pyright", "hmx-ls"]},
                "JavaScript": {"language_servers": ["vtsls", "hmx-ls"]},
                "Vue.js": {"language_servers": ["vue-language-server", "hmx-ls"]},
            },
        }
        print("// Put this in .zed/settings.json:")
        print(json.dumps(config, indent=2))
    elif target == "omp":
        config = {
            "mcp_servers": {
                "hmx": {
                    "command": py_bin,
                    "args": ["-m", "hmx_ls.cli", "mcp"],
                }
            }
        }
        print("# Put this in .omp/agent/config.yml or ~/.omp/agent/config.yml:")
        print(json.dumps(config, indent=2))
    elif target in ("claude", "codex"):
        config = {
            "mcpServers": {
                "hmx-lsp": {
                    "command": py_bin,
                    "args": ["-m", "hmx_ls.cli", "mcp"],
                }
            }
        }
        print(f"// Put this in .mcp.json or claude_desktop_config.json:")
        print(json.dumps(config, indent=2))
    else:
        print(f"Unknown setup target '{target}'. Choose from: vscode, zed, omp, claude, codex")
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="hmx-ls", description="HMX Language Server CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve", help="Run LSP server over stdio for IDEs (VS Code, PyCharm, Zed)")

    p_mcp = sub.add_parser("mcp", help="Run Model Context Protocol (MCP) server for AI assistants (Claude, Codex, OMP)")
    p_mcp.add_argument("--root", help="Path to HMX repository root")

    p_check = sub.add_parser("check", help="Run cross-layer validation diagnostics gate")
    p_check.add_argument("--root", help="Path to HMX repository root")

    p_inspect = sub.add_parser("inspect", help="Inspect model inheritance, composed fields, and methods")
    p_inspect.add_argument("model", help="Technical model name (e.g. hremployee)")
    p_inspect.add_argument("--root", help="Path to HMX repository root")

    p_where = sub.add_parser("where-used", help="Find usages of model or field across 4 layers")
    p_where.add_argument("model", help="Technical model name (e.g. hremployee)")
    p_where.add_argument("field", nargs="?", default="", help="Optional field name")
    p_where.add_argument("--root", help="Path to HMX repository root")

    p_setup = sub.add_parser("setup", help="Print configuration snippet for an editor or AI assistant")
    p_setup.add_argument("target", choices=["vscode", "zed", "omp", "claude", "codex", "jetbrains"], help="Target editor or AI harness")

    args = parser.parse_args()
    dispatch = {
        "serve": cmd_serve,
        "mcp": cmd_mcp,
        "check": cmd_check,
        "inspect": cmd_inspect,
        "where-used": cmd_where_used,
        "setup": cmd_setup,
    }
    sys.exit(dispatch[args.command](args))


if __name__ == "__main__":
    main()
