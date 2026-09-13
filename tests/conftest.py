from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolated_cache_home():
    with tempfile.TemporaryDirectory(prefix="hmx-ls-test-cache-") as home:
        previous = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = home
        try:
            yield home
        finally:
            if previous is None:
                os.environ.pop("XDG_CACHE_HOME", None)
            else:
                os.environ["XDG_CACHE_HOME"] = previous
