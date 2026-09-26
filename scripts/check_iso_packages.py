#!/usr/bin/env python3
"""Fail if the ISO was built against stale ashlaros-* packages.

build-iso and build-packages are independent workflows. A push touching both
`packages/` and `installer/` triggers both, and build-iso's pacstrap runs
against ashlaros.download/packages, which keeps serving the previous build
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
import seed_install_cache  # noqa: E402
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


def unstaged_requests(rootfs: Path) -> list[str]:
    """Packages the installer will ask for that the medium cannot answer.

    The ISO must be able to install with no network at all, and it answers
    a package from one of two places: unpacked in the live root, which the
    installer copies onto the target (livecopy.py), or staged as a tarball
    in the cache. Either satisfies a request; neither means an offline
    install stops partway through with the disk already written.

    Both halves, because the cache alone is no longer the whole story. It
    used to be, and this check asserted exactly that - which is why it
    failed the first build after the cache was pruned to what the medium
    lacks, correctly by its own lights and wrongly by the design's.

    Names only, not the closure. A name is what install_system asks for;
    if pacman resolved a name at stage time it staged its dependencies
    too, so a complete set of names with a complete stage behind each is
    the whole invariant. Checking the closure here would mean resolving it
    a second way and disagreeing with pacman about providers.

    The lists are read with seed_install_cache's own parsers: a second copy
    here would disagree with the staging the first time either file changed
    shape, and disagree silently.
    """
    requested = set(seed_install_cache.requested_packages())

    cache = rootfs / seed_install_cache.cache_path().relative_to("/")
    cached = {
        path.name.rsplit("-", 3)[0]
        for path in cache.glob("*.pkg.tar.*")
        if path.suffix != ".sig"
    }
    return sorted(requested - cached - installed_in_rootfs(rootfs))


def installed_in_rootfs(rootfs: Path) -> set[str]:
    """Package names libalpm unpacked into the medium.

    These need no tarball: the installer copies the live root onto the
    target rather than installing them a second time, which is what took
    1256 MiB off the ISO (#104).
    """
    local = rootfs / "var/lib/pacman/local"
    try:
        entries = [path.name for path in local.iterdir() if path.is_dir()]
    except OSError:
        return set()
    # <name>-<pkgver>-<pkgrel>, and a name may itself contain dashes
    return {entry.rsplit("-", 2)[0] for entry in entries}


def staged_databases(rootfs: Path) -> list[str]:
    """The sync databases staged beside the cache.

    A cache of packages cannot be installed from on its own: pacman
    resolves a name against a database before it looks for a file, so with
    no database every target is "not found" however full the cache is.
    That is not a theoretical gap - it is how an offline install failed two
    minutes in with the disk already partitioned.

    Checked here because the failure is invisible until someone installs
    without a network: every CI test-install has mirrors and would pass
    with an empty database directory.
    """
    database_dir = rootfs / seed_install_cache.cache_path().parent.relative_to("/") / "db"
    return sorted(path.name for path in database_dir.glob("sync/*.db"))


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

    missing = unstaged_requests(args.rootfs)
    if missing:
        print(
            "these packages are requested by the installer but are not staged "
            "in the ISO's cache, so an install with no network stops partway "
            f"through with the disk already written: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    databases = staged_databases(args.rootfs)
    if not databases:
        print(
            "the ISO stages packages but no sync databases, so pacman cannot "
            "resolve a single name without a network and an offline install "
            "fails after partitioning the disk",
            file=sys.stderr,
        )
        return 1
    print(f"{len(databases)} package databases staged: {', '.join(databases)}")

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
