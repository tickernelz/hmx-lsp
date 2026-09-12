from __future__ import annotations

import os
import sys
from lsprotocol import types
from mcp.server.fastmcp import FastMCP

from hmx_core.cache import load
from hmx_core.index import Index, build, python_files
from hmx_core.resolve import Resolver
from hmx_ls.cursor.common import path_to_uri
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics
from hmx_ls.features.hover import resolve_hover
from hmx_ls.features.references import resolve_references

mcp = FastMCP("hmx-lsp")

_ROOT = os.environ.get("HMX_ROOT") or os.getcwd()
_INDEX: Index | None = None
_RESOLVER: Resolver | None = None


def _get_server():
    global _INDEX, _RESOLVER
    if _INDEX is None:
        py_paths = python_files(_ROOT)
        cached = load(_ROOT, py_paths)
        if cached is not None:
            _INDEX = cached
        else:
            _INDEX = build(_ROOT)
        _RESOLVER = Resolver(_INDEX)

    class MockWorkspace:
        def get_text_document(self, uri):
            return None

    class ServerBridge:
        root = _ROOT
        index = _INDEX
        resolver = _RESOLVER
        workspace = MockWorkspace()

    return ServerBridge()


@mcp.tool()
def hmx_definition(file_path: str, line: int, col: int) -> list[dict]:
    s = _get_server()
    abs_path = os.path.abspath(file_path) if not os.path.isabs(file_path) else file_path
    uri = path_to_uri(abs_path)
    pos = types.Position(line=max(0, line - 1), character=col)
    locs = resolve_definition(s, uri, pos)
    return [
        {
            "uri": loc.uri,
            "path": loc.uri.replace("file://", ""),
            "line": loc.range.start.line + 1,
            "col": loc.range.start.character,
        }
        for loc in locs
    ]


@mcp.tool()
def hmx_hover(file_path: str, line: int, col: int) -> str:
    s = _get_server()
    abs_path = os.path.abspath(file_path) if not os.path.isabs(file_path) else file_path
    uri = path_to_uri(abs_path)
    pos = types.Position(line=max(0, line - 1), character=col)
    h = resolve_hover(s, uri, pos)
    return h.contents.value if h else "No hover information found."


@mcp.tool()
def hmx_model_info(model_name: str) -> dict:
    s = _get_server()
    norm = model_name.lower().replace(".", "").replace("_", "")
    if not s.resolver.known(norm):
        return {"error": f"Unknown model '{model_name}'"}
    entry = s.index.models.get(norm)
    fields = s.resolver.fields(norm)
    methods = s.resolver.methods(norm)
    return {
        "model": norm,
        "sites": [str(loc) for loc in (entry.sites if entry else [])],
        "parents": sorted(entry.edges if entry else []),
        "composed_field_count": len(fields),
        "composed_fields": sorted(fields.keys()),
        "composed_method_count": len(methods),
        "composed_methods": sorted(methods.keys()),
    }


@mcp.tool()
def hmx_where_used(model_name: str, field_name: str = "") -> list[dict]:
    s = _get_server()
    norm = model_name.lower().replace(".", "").replace("_", "")
    results = []
    if field_name:
        fields = s.resolver.fields(norm)
        loc = fields.get(field_name)
        if loc:
            results.append({"type": "declaration", "path": loc.path, "line": loc.line, "col": loc.col})
    else:
        entry = s.index.models.get(norm)
        if entry:
            for s_loc in entry.sites:
                results.append({"type": "python_class", "path": s_loc.path, "line": s_loc.line})
            for xid in s.index.xmlids.models.get(norm, []):
                xe = s.index.xmlids.entries.get(xid)
                if xe:
                    results.append({"type": "xml_view_record", "xmlid": xid, "path": xe.loc.path, "line": xe.loc.line})
            for acl in s.index.security.acls_for_model(norm):
                results.append({"type": "security_csv", "path": acl.loc.path, "line": acl.loc.line})
    return results


@mcp.tool()
def hmx_diagnose(file_path: str) -> list[dict]:
    s = _get_server()
    abs_path = os.path.abspath(file_path) if not os.path.isabs(file_path) else file_path
    uri = path_to_uri(abs_path)
    diags = compute_diagnostics(s, uri)
    return [
        {
            "code": d.code,
            "message": d.message,
            "severity": str(d.severity),
            "line": d.range.start.line + 1,
            "col": d.range.start.character,
        }
        for d in diags
    ]


def run_mcp() -> None:
    mcp.run()


if __name__ == "__main__":
    run_mcp()
