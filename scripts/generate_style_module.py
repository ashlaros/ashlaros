#!/usr/bin/env python3
"""Generate the worker's copies of docs/site.css and docs/background.svg.

docs/ is bound as static assets on the apex only, so the worker cannot
read the file at runtime to serve it on packages. and iso. as well. It
carries the bytes instead - the same shape favicon.js already uses - and
this keeps that copy honest rather than leaving two stylesheets to drift.

The alternative was fetching the apex from the worker on every request for
a stylesheet, which is a network round trip and a hard dependency between
two hostnames for something that never changes between deploys.
"""

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# (source, target, export name, what it is)
ASSETS = [
    (
        ROOT / "docs" / "site.css",
        ROOT / "worker" / "src" / "style.js",
        "STYLESHEET",
        "stylesheet",
    ),
    (
        ROOT / "docs" / "background.svg",
        ROOT / "worker" / "src" / "background.js",
        "BACKGROUND",
        "background",
    ),
]


def module(source: pathlib.Path, name: str) -> str:
    body = source.read_text().strip()
    # a backtick or ${ would end or interpolate the template literal;
    # neither belongs in css or an svg, so this refuses rather than
    # escaping and producing bytes that differ from the source
    if "`" in body or "${" in body:
        raise SystemExit(f"{source.name} contains a backtick or ${{")
    relative = source.relative_to(ROOT)
    return (
        f"// Generated from {relative} by scripts/generate_style_module.py.\n"
        f"// Edit {relative.name}, not this file.\n"
        "//\n"
        "// The worker serves this on every hostname, because docs/ is bound as\n"
        "// static assets on the apex alone and packages. and iso. need the same\n"
        "// bytes from their own origin.\n"
        f"export const {name} = `{body}\n`;\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if stale")
    args = parser.parse_args()

    stale = []
    for source, target, name, _kind in ASSETS:
        wanted = module(source, name)
        current = target.read_text() if target.exists() else None
        if current == wanted:
            continue
        stale.append((source, target, wanted))

    if args.check:
        if stale:
            names = ", ".join(str(t.relative_to(ROOT)) for _s, t, _w in stale)
            print(f"out of date: {names}", file=sys.stderr)
            print("run scripts/generate_style_module.py", file=sys.stderr)
            return 1
        print("the worker's copies match docs/")
        return 0

    if not stale:
        print("already up to date")
        return 0
    for _source, target, wanted in stale:
        target.write_text(wanted)
        print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
