#!/usr/bin/env python3
"""Split packages/ into build waves, and within a wave into `any` and compiled.

Two things decide the shape of a run:

  - `arch=any` packages build once and are registered in both databases;
    anything else builds per architecture. Read out of each PKGBUILD's own
    arch= line, so there is no second list to drift.

  - A package that depends on another package built here cannot be built in
    the same wave: the dependency has to be published before makepkg can
    resolve it. flashfocus needs python-xpybutil, and Arch packages neither.
    Wave 0 is everything with no such dependency; wave 1 is what depends on
    wave 0, and so on.

Writes GitHub Actions outputs on stdout.
"""

import json
import os
import re
import sys
from pathlib import Path

PACKAGES = Path(__file__).resolve().parent.parent / "packages"

ARCH_RE = re.compile(r"^arch=\((.*?)\)", re.MULTILINE | re.DOTALL)
# depends and makedepends both have to exist before the build starts;
# optdepends do not, so they are deliberately absent here
DEPENDS_RE = re.compile(r"^(?:make)?depends=\((.*?)\)", re.MULTILINE | re.DOTALL)
PKGNAME_RE = re.compile(r"^pkgname=(.+)$", re.MULTILINE)


def field(pattern: re.Pattern, text: str) -> list[str]:
    """Every quoted or bare word in the first matching array assignment."""
    match = pattern.search(text)
    if not match:
        return []
    body = re.sub(r"#.*", "", match.group(1))
    return re.findall(r"[\w.+-]+", body.replace("'", " ").replace('"', " "))


def pkgname_of(pkgbuild: Path) -> str:
    match = PKGNAME_RE.search(pkgbuild.read_text())
    # a PKGBUILD without a pkgname would fail makepkg long before this
    name = match.group(1).strip().strip("'\"") if match else pkgbuild.parent.name
    return name.replace("${pkgname}", pkgbuild.parent.name)


def is_any(text: str, pkgbuild: Path) -> bool:
    arches = field(ARCH_RE, text)
    if not arches:
        raise SystemExit(f"{pkgbuild}: no arch= line")
    return arches == ["any"]


def main() -> int:
    only = os.environ.get("ONLY", "").strip()

    packages = {}
    for pkgbuild in sorted(PACKAGES.glob("*/PKGBUILD")):
        text = pkgbuild.read_text()
        packages[pkgbuild.parent.name] = {
            "pkgname": pkgname_of(pkgbuild),
            "any": is_any(text, pkgbuild),
            "depends": field(DEPENDS_RE, text),
        }

    if only:
        if only not in packages:
            raise SystemExit(f"no package directory named {only}")
        packages = {only: packages[only]}

    provided = {meta["pkgname"]: name for name, meta in packages.items()}

    waves = []
    remaining = dict(packages)
    published: set[str] = set()
    while remaining:
        ready = {
            name: meta
            for name, meta in remaining.items()
            # only dependencies we build ourselves can hold a package back;
            # everything else comes from Arch or CachyOS and is already there
            if not {
                provided[d] for d in meta["depends"] if d in provided and provided[d] != name
            }
            - published
        }
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise SystemExit(f"dependency cycle among: {cycle}")

        waves.append(
            {
                "any": sorted(n for n, m in ready.items() if m["any"]),
                "compiled": sorted(n for n, m in ready.items() if not m["any"]),
            }
        )
        published |= {m["pkgname"] for m in ready.values()}
        for name in ready:
            del remaining[name]

    print(f"waves={json.dumps(waves)}")
    print(f"wave_count={len(waves)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
