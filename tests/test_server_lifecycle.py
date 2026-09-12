from __future__ import annotations

import os
from pathlib import Path
from lsprotocol import types
from pygls.workspace import Workspace

from hmx_ls.server import (
    on_completion,
    on_definition,
    on_hover,
    on_initialize,
    server,
)


def test_server_initialization_and_queries(tmp_path: Path):
    server.protocol._workspace = Workspace(tmp_path.as_uri())

    init_params = types.InitializeParams(
        capabilities=types.ClientCapabilities(),
        root_uri=tmp_path.as_uri(),
    )
    result = on_initialize(init_params)
    assert result.capabilities.definition_provider is not None
    assert result.capabilities.hover_provider is not None
    assert result.capabilities.completion_provider is not None

    server._index_ready.wait(timeout=2)
    if server._bg_thread:
        server._bg_thread.join(timeout=2)

    server.root = str(tmp_path)
    emp = server.index.entry("hremployee")
    emp.declared["name"] = None
    server.resolver.invalidate()

    xml_file = tmp_path / "test.xml"
    xml_content = """<record id="v1" model="baseuiview">
    <field name="model">hremployee</field>
    <field name="arch" type="xml">
        <form>
            <field name="name" />
        </form>
    </field>
</record>"""
    xml_file.write_text(xml_content, encoding="utf-8")
    uri = xml_file.as_uri()

    pos = types.Position(line=4, character=26)
    comp = on_completion(types.CompletionParams(
        text_document=types.TextDocumentIdentifier(uri=uri),
        position=pos,
    ))
    labels = [i.label for i in comp.items]
    assert "name" in labels

    hover = on_hover(types.HoverParams(
        text_document=types.TextDocumentIdentifier(uri=uri),
        position=pos,
    ))
    assert hover is not None
    assert "hremployee" in hover.contents.value
