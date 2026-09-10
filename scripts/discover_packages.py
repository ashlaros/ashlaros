#!/usr/bin/env python3
"""Split packages/ into the `any` set and the compiled set.

An `arch=any` package builds once and is registered in both databases;
anything else builds per architecture. The split is read out of each
PKGBUILD's own arch= line, so there is no second list to drift.

Writes GitHub Actions outputs on stdout.
"""

import json
import os
import re
import sys
from pathlib import Path

PACKAGES = Path(__file__).resolve().parent.parent / "packages"

ARCH_RE = re.compile(r"^arch=\((.*?)\)", re.MULTILINE | re.DOTALL)


def is_any(pkgbuild: Path) -> bool:
    match = ARCH_RE.search(pkgbuild.read_text())
    if not match:
        raise SystemExit(f"{pkgbuild}: no arch= line")
    arches = match.group(1).replace("'", " ").replace('"', " ").split()
    return arches == ["any"]


def main() -> int:
    only = os.environ.get("ONLY", "").strip()

    any_packages, compiled = [], []
    for pkgbuild in sorted(PACKAGES.glob("*/PKGBUILD")):
        name = pkgbuild.parent.name
        if only and name != only:
            continue
        (any_packages if is_any(pkgbuild) else compiled).append(name)

    if only and not (any_packages or compiled):
        raise SystemExit(f"no package directory named {only}")

    print(f"any={json.dumps(any_packages)}")
    print(f"compiled={json.dumps(compiled)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
