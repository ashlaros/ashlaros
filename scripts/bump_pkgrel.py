#!/usr/bin/env python3
"""Bump a vendored package's pkgrel so a rebuild gets a filename of its own.

Rebuilding a package at an unchanged version cannot be published: the file
name is derived from pkgver-pkgrel, and publish.py refuses to replace an
object that the live database already names, because the worker serves it as
`immutable, max-age=31536000` and a reader mid-upload would get one build's
package with another build's signature. So a toolchain rebuild is a pkgrel
bump, not a mode.

The bump is decimal - 1 becomes 1.1 - which is Arch's own convention for a
rebuild that carries no upstream change. It matters here for a specific
reason: track-upstreams.yml takes upstream's PKGBUILD verbatim, so the next
upstream release sets pkgrel back to a small integer. Integer-bumping to 2
would then collide with upstream's own 2, and vercmp would call the two
equal. 1.1 sorts above 1 and below 2, so an upstream bump always wins.
Verified with vercmp: 1.1 > 1, 2 > 1.1, 1.10 > 1.9.

Authored packages are refused rather than bumped. Their version is derived
from git history by package_version.py - pkgrel is the count of commits
touching the directory - so the commit that records a rebuild increments it
already, and editing the PKGBUILD here would be overwritten at build time.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# packages whose content is authored here take their version from git
AUTHORED_PREFIX = "ashlaros-"

PKGREL_RE = re.compile(r"^(pkgrel=)(['\"]?)([0-9.]+)(['\"]?)\s*$", re.MULTILINE)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def next_pkgrel(current: str) -> str:
    """1 -> 1.1, 1.1 -> 1.2, 2.9 -> 2.10.

    Only the fractional part moves: the integer part is upstream's, and
    raising it would shadow the next real upstream release.
    """
    if "." in current:
        whole, fraction = current.split(".", 1)
        # a second dot is not a pkgrel this understands; refusing beats
        # writing a version pacman would order in a way nobody intended
        if "." in fraction:
            raise SystemExit(f"cannot bump pkgrel={current}: more than one dot")
        return f"{whole}.{int(fraction) + 1}"
    return f"{current}.1"


def bump(directory: Path) -> tuple[str, str]:
    """Rewrite one PKGBUILD's pkgrel, returning (before, after)."""
    if directory.name.startswith(AUTHORED_PREFIX):
        raise SystemExit(
            f"{directory.name} is authored here; its pkgrel is the commit count "
            "package_version.py derives, so a rebuild needs a commit, not an edit"
        )

    pkgbuild = directory / "PKGBUILD"
    if not pkgbuild.is_file():
        raise SystemExit(f"{directory}: no PKGBUILD")

    text = pkgbuild.read_text()
    match = PKGREL_RE.search(text)
    if not match:
        raise SystemExit(f"{directory.name}: no pkgrel= line to bump")

    prefix, open_quote, current, close_quote = match.groups()
    updated = next_pkgrel(current)
    pkgbuild.write_text(
        text[: match.start()]
        + f"{prefix}{open_quote}{updated}{close_quote}\n"
        + text[match.end() :]
    )
    return current, updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", nargs="+", help="package directory names")
    args = parser.parse_args()

    for name in args.package:
        directory = ROOT / "packages" / name
        if not directory.is_dir():
            raise SystemExit(f"no package directory named {name}")
        before, after = bump(directory)
        log(f"{name}: pkgrel {before} -> {after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
