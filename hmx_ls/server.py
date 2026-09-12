from __future__ import annotations

import asyncio
import os
import threading
from lsprotocol import types
from pygls.lsp.server import LanguageServer

from hmx_core.cache import load, save
from hmx_core.index import Index, build, python_files
from hmx_core.resolve import Resolver
from hmx_ls.cursor.common import uri_to_path
from hmx_ls.features.code_actions import resolve_code_actions
from hmx_ls.features.completion import resolve_completion
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics
from hmx_ls.features.document_link import resolve_document_links
from hmx_ls.features.hover import resolve_hover
from hmx_ls.features.references import resolve_references
from hmx_ls.features.rename import prepare_rename, resolve_rename
from hmx_ls.features.symbols import resolve_document_symbols, resolve_workspace_symbols


class HmxLanguageServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root: str = ""
        self.index: Index = Index()
        self.resolver: Resolver = Resolver(self.index)
        self._index_ready: threading.Event = threading.Event()
        self._debounce_tasks: dict[str, asyncio.Task] = {}


server = HmxLanguageServer("hmx-ls", "0.1.0")


def _bg_index_worker(ls: HmxLanguageServer, root: str) -> None:
    py_paths = python_files(root)
    cached = load(root, py_paths)
    if cached is not None:
        ls.index = cached
        ls.resolver = Resolver(cached)
        ls._index_ready.set()
        return

    fresh_index = build(root)
    ls.index = fresh_index
    ls.resolver = Resolver(fresh_index)
    save(root, py_paths, fresh_index)
    ls._index_ready.set()


@server.feature(types.INITIALIZE)
def on_initialize(params: types.InitializeParams) -> types.InitializeResult:
    root = ""
    if params.root_uri:
        root = uri_to_path(params.root_uri)
    elif params.root_path:
        root = params.root_path
    elif params.workspace_folders:
        root = uri_to_path(params.workspace_folders[0].uri)

    if not root:
        root = os.getcwd()

    server.root = os.path.abspath(root)

    threading.Thread(target=_bg_index_worker, args=(server, server.root), daemon=True).start()

    return types.InitializeResult(
        capabilities=types.ServerCapabilities(
            text_document_sync=types.TextDocumentSyncOptions(
                open_close=True,
                change=types.TextDocumentSyncKind.Incremental,
                save=types.SaveOptions(include_text=True),
            ),
            definition_provider=types.DefinitionOptions(),
            hover_provider=types.HoverOptions(),
            completion_provider=types.CompletionOptions(
                trigger_characters=['"', "'", ".", "<", "/", "@"],
                resolve_provider=False,
            ),
            document_symbol_provider=True,
            workspace_symbol_provider=True,
            references_provider=True,
            code_action_provider=True,
            rename_provider=types.RenameOptions(prepare_provider=True),
            document_link_provider=types.DocumentLinkOptions(resolve_provider=False),
        )
    )


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def on_did_open(params: types.DidOpenTextDocumentParams) -> None:
    uri = params.text_document.uri
    diags = compute_diagnostics(server, uri)
    server.publish_diagnostics(uri, diags)


async def _debounced_diagnostics(uri: str) -> None:
    await asyncio.sleep(0.15)
    diags = compute_diagnostics(server, uri)
    server.publish_diagnostics(uri, diags)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def on_did_change(params: types.DidChangeTextDocumentParams) -> None:
    uri = params.text_document.uri
    task = server._debounce_tasks.get(uri)
    if task and not task.done():
        task.cancel()
    loop = asyncio.get_event_loop()
    server._debounce_tasks[uri] = loop.create_task(_debounced_diagnostics(uri))


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def on_did_save(params: types.DidSaveTextDocumentParams) -> None:
    uri = params.text_document.uri
    path = uri_to_path(uri)
    rel = os.path.relpath(path, server.root) if server.root else path
    doc = server.workspace.get_text_document(uri)
    content = doc.source.encode("utf-8") if doc else b""

    affected = server.index.update_file(rel, content)
    server.resolver.invalidate(affected)

    diags = compute_diagnostics(server, uri)
    server.publish_diagnostics(uri, diags)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def on_did_close(params: types.DidCloseTextDocumentParams) -> None:
    uri = params.text_document.uri
    task = server._debounce_tasks.pop(uri, None)
    if task and not task.done():
        task.cancel()
    server.publish_diagnostics(uri, [])


@server.feature(types.TEXT_DOCUMENT_DEFINITION)
def on_definition(params: types.DefinitionParams) -> list[types.Location]:
    return resolve_definition(server, params.text_document.uri, params.position)


@server.feature(types.TEXT_DOCUMENT_HOVER)
def on_hover(params: types.HoverParams) -> types.Hover | None:
    return resolve_hover(server, params.text_document.uri, params.position)


@server.feature(types.TEXT_DOCUMENT_COMPLETION)
def on_completion(params: types.CompletionParams) -> types.CompletionList:
    return resolve_completion(server, params.text_document.uri, params.position)


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
def on_document_symbol(params: types.DocumentSymbolParams) -> list[types.DocumentSymbol]:
    return resolve_document_symbols(server, params.text_document.uri)


@server.feature(types.WORKSPACE_SYMBOL)
def on_workspace_symbol(params: types.WorkspaceSymbolParams) -> list[types.WorkspaceSymbol]:
    return resolve_workspace_symbols(server, params.query)


@server.feature(types.TEXT_DOCUMENT_REFERENCES)
def on_references(params: types.ReferenceParams) -> list[types.Location]:
    return resolve_references(server, params.text_document.uri, params.position)


@server.feature(types.TEXT_DOCUMENT_CODE_ACTION)
def on_code_action(params: types.CodeActionParams) -> list[types.CodeAction]:
    return resolve_code_actions(server, params.text_document.uri, params.range, params.context)


@server.feature(types.TEXT_DOCUMENT_PREPARE_RENAME)
def on_prepare_rename(params: types.PrepareRenameParams) -> types.PrepareRenamePlaceholder | None:
    return prepare_rename(server, params.text_document.uri, params.position)


@server.feature(types.TEXT_DOCUMENT_RENAME)
def on_rename(params: types.RenameParams) -> types.WorkspaceEdit | None:
    return resolve_rename(server, params.text_document.uri, params.position, params.new_name)


@server.feature(types.TEXT_DOCUMENT_DOCUMENT_LINK)
def on_document_link(params: types.DocumentLinkParams) -> list[types.DocumentLink]:
    return resolve_document_links(server, params.text_document.uri)


def main() -> None:
    server.start_io()


if __name__ == "__main__":
    main()
