from __future__ import annotations

import hashlib
import os
import pickle

FORMAT = 3


def _cache_home() -> str:
    return os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")


def path_for(root: str, name: str = "hmx-ls") -> str:
    key = hashlib.blake2b(os.path.abspath(root).encode(), digest_size=8).hexdigest()
    return os.path.join(_cache_home(), name, key, "index.pkl")


def _digest(root: str, paths: list[str]) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(str(FORMAT).encode())
    for p in sorted(paths):
        try:
            st = os.stat(p)
        except OSError:
            continue
        h.update(os.path.relpath(p, root).encode())
        h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
    return h.hexdigest()


def load(root: str, paths: list[str], name: str = "hmx-ls"):
    target = path_for(root, name)
    if not os.path.isfile(target):
        return None
    try:
        blob = pickle.load(open(target, "rb"))
    except Exception:
        return None
    if blob.get("format") != FORMAT or blob.get("digest") != _digest(root, paths):
        return None
    return blob.get("index")


def save(root: str, paths: list[str], index, name: str = "hmx-ls") -> str:
    target = path_for(root, name)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump({"format": FORMAT, "digest": _digest(root, paths), "index": index},
                    fh, protocol=5)
    os.replace(tmp, target)
    return target
