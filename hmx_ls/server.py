from __future__ import annotations

import asyncio
import os
import threading

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from hmx_core.cache import load, save
from hmx_core.index import Index, build, indexed_files
from hmx_core.styles import StyleIndex, scan_styles
from hmx_core.resolve import Resolver
from hmx_ls import __version__
from hmx_ls.cursor.common import safe_relpath, uri_to_path
from hmx_ls.features.code_actions import resolve_code_actions
from hmx_ls.features.code_lens import resolve_code_lens
from hmx_ls.features.completion import resolve_completion
from hmx_ls.features.definition import resolve_definition
from hmx_ls.features.diagnostics import compute_diagnostics
from hmx_ls.features.document_link import resolve_document_links
from hmx_ls.features.folding import resolve_folding_ranges
from hmx_ls.features.hover import resolve_hover
from hmx_ls.features.inlay import resolve_inlay_hints
from hmx_ls.features.references import resolve_references
from hmx_ls.features.rename import prepare_rename, resolve_rename
from hmx_ls.features.semantic import SEMANTIC_LEGEND, resolve_semantic_tokens
from hmx_ls.features.symbols import resolve_document_symbols, resolve_workspace_symbols

DEBOUNCE_SECONDS = 0.15


class HmxLanguageServer(LanguageServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root: str = ""
        self.index: Index = Index()
        self.resolver: Resolver = Resolver(self.index)
        self._index_ready: threading.Event = threading.Event()
        self._debounce_tasks: dict[str, asyncio.Task] = {}
        self._bg_thread: threading.Thread | None = None
        self._styles: StyleIndex | None = None

    @property
    def styles(self) -> StyleIndex:
        if self._styles is None:
            self._styles = scan_styles(self.root) if self.root else StyleIndex()
        return self._styles


server = HmxLanguageServer("hmx-ls", __version__)


def _publish_open_documents() -> None:
    workspace = getattr(server, "workspace", None)
    if workspace is None:
        return
    for uri in list(getattr(workspace, "text_documents", {})):
        try:
            _send_diagnostics(uri, compute_diagnostics(server, uri))
        except Exception:
            continue


def _bg_index_worker(ls: HmxLanguageServer, root: str) -> None:
    try:
        if not root or not os.path.isdir(os.path.join(root, "hmx")):
            return
        paths = indexed_files(root)
        cached = load(root, paths)
        if cached is not None:
            ls.index = cached
            ls.resolver = Resolver(cached)
            return
        fresh = build(root)
        ls.index = fresh
        ls.resolver = Resolver(fresh)
        save(root, paths, fresh)
    finally:
        ls._index_ready.set()
        _publish_open_documents()


@server.feature(types.INITIALIZE)
def on_initialize(params: types.InitializeParams) -> types.InitializeResult:
    root = ""
    if params.root_uri:
        root = uri_to_path(params.root_uri)
    elif params.root_path:
        root = params.root_path
    elif params.workspace_folders:
        root = uri_to_path(params.workspace_folders[0].uri)
    server.root = os.path.abspath(root or os.getcwd())

    worker = threading.Thread(target=_bg_index_worker, args=(server, server.root), daemon=True)
    server._bg_thread = worker
    worker.start()

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
                trigger_characters=['"', "'", ".", "<", "/", "@", ",", "("],
                resolve_provider=False,
            ),
            document_symbol_provider=True,
            workspace_symbol_provider=True,
            references_provider=True,
            code_action_provider=True,
            rename_provider=types.RenameOptions(prepare_provider=True),
            document_link_provider=types.DocumentLinkOptions(resolve_provider=False),
            semantic_tokens_provider=types.SemanticTokensOptions(
                legend=SEMANTIC_LEGEND, full=True),
            inlay_hint_provider=types.InlayHintOptions(resolve_provider=False),
            folding_range_provider=True,
            code_lens_provider=types.CodeLensOptions(resolve_provider=False),
        ),
        server_info=types.ServerInfo(name="hmx-ls", version=__version__),
    )


def _publish(uri: str) -> None:
    if not server._index_ready.is_set():
        return
    _send_diagnostics(uri, compute_diagnostics(server, uri))


def _send_diagnostics(uri: str, diagnostics: list[types.Diagnostic]) -> None:
    server.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
    )


async def _debounced(uri: str) -> None:
    await asyncio.sleep(DEBOUNCE_SECONDS)
    _publish(uri)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def on_did_open(params: types.DidOpenTextDocumentParams) -> None:
    _publish(params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
def on_did_change(params: types.DidChangeTextDocumentParams) -> None:
    uri = params.text_document.uri
    pending = server._debounce_tasks.get(uri)
    if pending and not pending.done():
        pending.cancel()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _publish(uri)
        return
    server._debounce_tasks[uri] = loop.create_task(_debounced(uri))


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def on_did_save(params: types.DidSaveTextDocumentParams) -> None:
    uri = params.text_document.uri
    rel = safe_relpath(uri_to_path(uri), server.root)
    doc = server.workspace.get_text_document(uri)
    content = doc.source.encode("utf-8") if doc else b""
    affected = server.index.update_file(rel, content)
    server.resolver.invalidate(affected)
    if rel.endswith((".css", ".scss")):
        server._styles = None
    _publish(uri)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def on_did_close(params: types.DidCloseTextDocumentParams) -> None:
    uri = params.text_document.uri
    pending = server._debounce_tasks.pop(uri, None)
    if pending and not pending.done():
        pending.cancel()
    _send_diagnostics(uri, [])


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


@server.feature(types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL)
def on_semantic_tokens(params: types.SemanticTokensParams) -> types.SemanticTokens:
    return resolve_semantic_tokens(server, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_INLAY_HINT)
def on_inlay_hint(params: types.InlayHintParams) -> list[types.InlayHint]:
    return resolve_inlay_hints(server, params.text_document.uri, params.range)


@server.feature(types.TEXT_DOCUMENT_FOLDING_RANGE)
def on_folding_range(params: types.FoldingRangeParams) -> list[types.FoldingRange]:
    return resolve_folding_ranges(server, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_CODE_LENS)
def on_code_lens(params: types.CodeLensParams) -> list[types.CodeLens]:
    return resolve_code_lens(server, params.text_document.uri)


def main() -> None:
    server.start_io()


if __name__ == "__main__":
    main()
