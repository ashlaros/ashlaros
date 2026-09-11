#!/usr/bin/env python3
"""Fail if the ISO was built against stale ashlaros-* packages.

build-iso and build-packages are independent workflows. A push touching both
`packages/` and `installer/` triggers both, and build-iso's pacstrap runs
against packages.ashlaros.download, which keeps serving the previous build
until build-packages publishes. The ISO comes out green carrying code from
the commit before, and nothing says so - the only way to notice is to
unsquash the image and read the file.

That silence is the expensive part: a verification loop is fetch, install,
check, about 45 minutes, and a stale ISO wastes all of it while looking like
the fix under test did not work.

So compare what the built rootfs actually installed against what this commit
would produce, and fail loudly when it is behind.

Needs full history, same as package_version.py - actions/checkout with
fetch-depth: 0, or every derived version is <date>-1 and the comparison is
meaningless.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"

sys.path.insert(0, str(ROOT / "scripts"))
from package_version import NoHistory, version_of  # noqa: E402


class UnreadableRootfs(Exception):
    """The built rootfs has no readable package database."""


def trust_checkout() -> None:
    """Let git read this checkout's history inside a container.

    The workflow runs in a container, so the checkout is owned by a different
    uid than the one running git, and git refuses it as dubious ownership -
    which surfaces here as "not a git repository" and every version
    underivable. build-package.sh does the same thing for the same reason.
    """
    subprocess.run(
        ["git", "config", "--global", "--add", "safe.directory", str(ROOT)],
        check=False,
        capture_output=True,
    )


def installed_versions(rootfs: Path) -> dict[str, str]:
    """{name: version} for every ashlaros-* package in a built rootfs.

    Read with pacman -Qr rather than parsing the database: the format is
    pacman's to change, and the ISO's own pacman is the authority on what
    it installed.
    """
    result = subprocess.run(
        ["pacman", "-Qr", str(rootfs)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # an empty or unreadable database is not staleness; say which it is
        # rather than dying in a traceback
        raise UnreadableRootfs(result.stderr.strip() or "pacman -Qr failed")
    versions = {}
    for line in result.stdout.splitlines():
        name, _, version = line.partition(" ")
        if name.startswith("ashlaros-"):
            versions[name] = version.strip()
    return versions


def expected_versions() -> dict[str, str]:
    """{name: version} every authored package would carry at HEAD."""
    expected = {}
    for directory in sorted(PACKAGES.iterdir()):
        if not directory.is_dir():
            continue
        version = version_of(directory)
        if version is not None:
            expected[directory.name] = f"{version[0]}-{version[1]}"
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rootfs",
        type=Path,
        required=True,
        help="mkarchiso work directory's airootfs, e.g. /tmp/work/x86_64/airootfs",
    )
    args = parser.parse_args()

    if not (args.rootfs / "var/lib/pacman").is_dir():
        print(f"no pacman database under {args.rootfs}", file=sys.stderr)
        return 2

    trust_checkout()

    try:
        expected = expected_versions()
    except NoHistory as exc:
        print(f"cannot derive versions: {exc}", file=sys.stderr)
        return 2

    try:
        installed = installed_versions(args.rootfs)
    except UnreadableRootfs as exc:
        print(f"cannot read the rootfs: {exc}", file=sys.stderr)
        return 2

    if not installed:
        print("no ashlaros-* packages in the rootfs", file=sys.stderr)
        return 2

    stale = []
    for name, want in sorted(expected.items()):
        got = installed.get(name)
        # a package this commit builds but the ISO does not install is not
        # staleness - iso/packages.x86_64 does not name every authored one
        if got is not None and got != want:
            stale.append((name, got, want))

    for name, got, want in stale:
        print(f"stale: {name} {got} installed, {want} expected", file=sys.stderr)

    if stale:
        print(
            "\nThe ISO was built before build-packages published this commit.\n"
            "Re-run build-iso once the packages are up.",
            file=sys.stderr,
        )
        return 1

    print(f"all {len(installed)} ashlaros-* packages match this commit")
    for name, version in sorted(installed.items()):
        print(f"  {name} {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
