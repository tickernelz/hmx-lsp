from __future__ import annotations

from typing import NamedTuple


class Loc(NamedTuple):
    path: str
    line: int
    col: int = 0
    end_line: int | None = None
    end_col: int | None = None

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.col}"


FRAMEWORK = Loc("<framework>", 0, 0)
