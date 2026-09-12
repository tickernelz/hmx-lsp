from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Callable

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

VERSION = r"\d+\.\d+\.\d+(?:[-+.][0-9A-Za-z.-]+)?"

_TOML_VERSION = re.compile(r'(?m)^[ \t]*version[ \t]*=[ \t]*"(' + VERSION + r')"')
_PY_VERSION = re.compile(r'(?m)^__version__[ \t]*=[ \t]*"(' + VERSION + r')"')
_GRADLE_PROPERTY = re.compile(r"(?m)^pluginVersion[ \t]*=[ \t]*(" + VERSION + r")[ \t]*$")
_GRADLE_FALLBACK = re.compile(
    r'gradleProperty\("pluginVersion"\)\.getOrElse\("(' + VERSION + r')"\)'
)
_JSON_VERSION = re.compile(r'"version"[ \t]*:[ \t]*"(' + VERSION + r')"')

Span = tuple[int, int]


class SiteError(Exception):
    pass


def _toml_section(text: str, header: str | None) -> Span:
    heads = [m.start() for m in re.finditer(r"(?m)^\[", text)]
    if header is None:
        return 0, heads[0] if heads else len(text)
    found = re.search(r"(?m)^\[" + re.escape(header) + r"\][^\n]*$", text)
    if found is None:
        raise SiteError(f"missing [{header}] section")
    after = [h for h in heads if h > found.end()]
    return found.end(), after[0] if after else len(text)


def toml_version(text: str, header: str | None) -> Span:
    lo, hi = _toml_section(text, header)
    found = _TOML_VERSION.search(text, lo, hi)
    if found is None:
        where = "top level" if header is None else f"[{header}]"
        raise SiteError(f"no version key at {where}")
    return found.span(1)


def python_dunder(text: str) -> Span:
    found = _PY_VERSION.search(text)
    if found is None:
        raise SiteError("no __version__ assignment")
    return found.span(1)


def gradle_property(text: str) -> Span:
    found = _GRADLE_PROPERTY.search(text)
    if found is None:
        raise SiteError("no pluginVersion property")
    return found.span(1)


def gradle_fallback(text: str) -> Span:
    found = _GRADLE_FALLBACK.search(text)
    if found is None:
        raise SiteError("no pluginVersion getOrElse fallback")
    return found.span(1)


def _json_depth(text: str, stop: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for char in text[:stop]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
    return depth


def json_version(text: str) -> Span:
    for found in _JSON_VERSION.finditer(text):
        if _json_depth(text, found.start()) == 1:
            return found.span(1)
    raise SiteError("no top-level version key")


@dataclass(frozen=True)
class Site:
    path: str
    locate: Callable[[str], Span]


SITES: tuple[Site, ...] = (
    Site("pyproject.toml", partial(toml_version, header="project")),
    Site("hmx_ls/__init__.py", python_dunder),
    Site("editors/jetbrains/gradle.properties", gradle_property),
    Site("editors/jetbrains/build.gradle.kts", gradle_fallback),
    Site("editors/zed/extension.toml", partial(toml_version, header=None)),
    Site("editors/zed/Cargo.toml", partial(toml_version, header="package")),
    Site("editors/vscode/package.json", json_version),
)

WIDTH = max(len(site.path) for site in SITES)


def _load(root: Path, site: Site) -> tuple[str, Span]:
    target = root / site.path
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise SiteError(f"{site.path}: unreadable ({exc.strerror})") from None
    try:
        return text, site.locate(text)
    except SiteError as exc:
        raise SiteError(f"{site.path}: {exc}") from None


def declared(root: Path, site: Site) -> str:
    text, (lo, hi) = _load(root, site)
    return text[lo:hi]


def rewrite(root: Path, site: Site, new_version: str) -> str:
    text, (lo, hi) = _load(root, site)
    previous = text[lo:hi]
    if previous != new_version:
        (root / site.path).write_text(text[:lo] + new_version + text[hi:], encoding="utf-8")
    return previous


def collect(root: Path) -> tuple[list[tuple[Site, str]], list[str]]:
    found: list[tuple[Site, str]] = []
    failures: list[str] = []
    for site in SITES:
        try:
            found.append((site, declared(root, site)))
        except SiteError as exc:
            failures.append(str(exc))
    return found, failures


def agreed_version(values: list[str]) -> str:
    unique = list(dict.fromkeys(values))
    return max(unique, key=values.count)


def run_check(root: Path, expect: str | None) -> int:
    found, failures = collect(root)
    for failure in failures:
        print(f"error: {failure}")
    if not found:
        return 1
    agreed = agreed_version([value for _, value in found])
    outliers = []
    for site, value in found:
        mark = "" if value == agreed else f"  MISMATCH (majority is {agreed})"
        print(f"{site.path:<{WIDTH}}  {value}{mark}")
        if value != agreed:
            outliers.append(site.path)
    if failures:
        return 1
    if outliers:
        print(f"drift: {len(outliers)} of {len(found)} declarations disagree")
        for path in outliers:
            print(f"  {path}")
        return 1
    if expect is not None and agreed != expect:
        print(f"drift: declarations agree on {agreed} but {expect} was expected")
        return 1
    print(f"ok: {len(found)} declarations agree on {agreed}")
    return 0


def run_bump(root: Path, new_version: str) -> int:
    if re.fullmatch(VERSION, new_version) is None:
        print(f"error: {new_version!r} is not a valid version")
        return 1
    changed = 0
    failures = 0
    for site in SITES:
        try:
            previous = rewrite(root, site, new_version)
        except SiteError as exc:
            print(f"error: {exc}")
            failures += 1
            continue
        if previous == new_version:
            print(f"{site.path:<{WIDTH}}  {previous} unchanged")
        else:
            print(f"{site.path:<{WIDTH}}  {previous} -> {new_version}")
            changed += 1
    print(f"{changed} of {len(SITES)} declarations rewritten to {new_version}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bump_version.py",
        description="Single writer for every declared HMX-LS version",
    )
    parser.add_argument("version", nargs="?", help="new version to write everywhere")
    parser.add_argument("--check", action="store_true", help="verify declarations agree")
    parser.add_argument("--expect", help="version the declarations must agree on")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="repository root")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.check:
        if args.version is not None:
            parser.error("--check takes no version argument")
        return run_check(root, args.expect)
    if args.version is None:
        parser.error("pass a version to write, or --check")
    if args.expect is not None:
        parser.error("--expect is only meaningful with --check")
    return run_bump(root, args.version)


if __name__ == "__main__":
    sys.exit(main())
