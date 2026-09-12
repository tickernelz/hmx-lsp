from __future__ import annotations

import os
from urllib.parse import unquote, urlparse
from lsprotocol import types
from hmx_core.locations import Loc


def uri_to_path(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        return os.path.abspath(unquote(parsed.path))
    return uri


def path_to_uri(path: str, root: str = "") -> str:
    if not os.path.isabs(path) and root:
        path = os.path.join(root, path)
    abs_path = os.path.abspath(path)
    return f"file://{abs_path}"


def loc_to_range(loc: Loc) -> types.Range:
    start_line = max(0, loc.line - 1)
    start_col = max(0, loc.col)
    end_line = max(0, (loc.end_line - 1) if loc.end_line is not None else start_line)
    end_col = max(start_col, loc.end_col if loc.end_col is not None else start_col + 1)
    return types.Range(
        start=types.Position(line=start_line, character=start_col),
        end=types.Position(line=end_line, character=end_col),
    )


def range_to_lsp(rng: tuple[tuple[int, int], tuple[int, int]] | None) -> types.Range:
    if rng is None:
        return types.Range(
            start=types.Position(line=0, character=0),
            end=types.Position(line=0, character=0),
        )
    (s_line, s_col), (e_line, e_col) = rng
    return types.Range(
        start=types.Position(line=max(0, s_line - 1), character=max(0, s_col)),
        end=types.Position(line=max(0, e_line - 1), character=max(0, e_col)),
    )
