#!/usr/bin/env python3
"""How many packages an install writes to the target.

The dashboard already knows how to fill the band between one phase's floor
and the next from the count of directories under the target's
var/lib/pacman/local (`installer/dashboard:97-104`) - it needs a
denominator, which it reads from
/usr/share/ashlaros-installer/expected-packages. Nothing ever wrote that
file, so `expected_package_count()` returned 0, the band was skipped, and
step 2 of 13 sat at three cells of forty for most of the install (#94).

Resolved rather than hand-maintained, for the reason
packages/ashlaros-branding generates its plymouth script from logo.txt: a
literal checked in beside the package lists is one that goes stale the
first time anybody adds a dependency, and the staleness is invisible - the
bar simply fills to the wrong place.

The closure is what the install writes, so it is what the dashboard
divides by: `base`, the configurator's own kernels and packages, and
DESKTOP_PACKAGES, resolved against the same pacman.conf the ISO uses so a
v3 package resolves to its v3 provider.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DESKTOP_PACKAGES_RE = re.compile(
    r"^DESKTOP_PACKAGES\s*[:=].*?[\(\[](.*?)[\)\]]\s*$",
    re.MULTILINE | re.DOTALL,
)
ENTRY = re.compile(r"""^\s*["']([\w.+@-]+)["']\s*,\s*$""", re.MULTILINE)


def desktop_packages() -> list[str]:
    """The names install_system() adds after the base system."""
    source = (ROOT / "installer" / "orchestrator" / "phases_impl.py").read_text()
    match = DESKTOP_PACKAGES_RE.search(source)
    if not match:
        raise SystemExit("expected_package_count: DESKTOP_PACKAGES not found")
    return ENTRY.findall(match.group(1))


def configurator_packages() -> list[str]:
    """The kernel and packages archinstall pacstraps before that."""
    source = (ROOT / "installer" / "configurator").read_text()
    names: list[str] = []
    for key in ("kernels", "packages"):
        match = re.search(rf'"{key}"\s*:\s*\[(.*?)\]', source, re.DOTALL)
        if not match:
            raise SystemExit(f"expected_package_count: {key} not in the configurator")
        names += re.findall(r'"([\w.+@-]+)"', match.group(1))
    return names


def count(pacman_conf: Path, dbpath: Path) -> int:
    wanted = ["base", *configurator_packages(), *desktop_packages()]
    result = subprocess.run(
        [
            "pacman", "-Sp", "--print-format", "%n",
            "--config", str(pacman_conf),
            "--dbpath", str(dbpath),
            "--noconfirm",
            *wanted,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return len({name for name in result.stdout.split() if name})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pacman-conf", type=Path, default=ROOT / "iso" / "pacman.conf",
        help="the configuration to resolve against, v3 repositories and all",
    )
    parser.add_argument(
        "--dbpath", type=Path, required=True,
        help="a synced database to resolve from",
    )
    parser.add_argument(
        "--output", type=Path,
        help="write the count here instead of stdout",
    )
    args = parser.parse_args()

    total = count(args.pacman_conf, args.dbpath)
    # A resolution that collapses to a handful of names means the lists were
    # not parsed, and a denominator of 12 would fill the bar in the first
    # seconds and then sit still - worse than the 0 it replaces.
    if total < 100:
        raise SystemExit(
            f"expected_package_count: resolved only {total} packages, which "
            "cannot be a full install - check the list parsing"
        )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{total}\n")
        print(f"expected packages: {total} -> {args.output}")
    else:
        print(total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
