#!/usr/bin/env python3
"""Stage the packages the installer will ask for into the live ISO.

The ISO carries every package an install needs, with dependencies, so the
install is a local copy rather than a network download and a machine with
no network can still be installed.

That is a deliberate reversal of #82, which staged the named packages
alone (--nodeps) and kept the install network-bound: 139 names against a
719-package closure meant 594 packages - glibc and alsa-lib among them -
were never on the medium, so the cache saved bandwidth and nothing more.
The cost is the one #82 priced and declined at the time: roughly 1.1 GiB
of packages and an ISO near 3.1 GB rather than 2.0, much of it a second
copy of files already unpacked in the same squashfs.

phases_impl.py points the live system's CacheDir at ISO_PACKAGE_CACHES and
falls through to the mirrors on a miss. This is the other half: putting
the packages there. Without it that CacheDir names an empty directory and
every install downloads everything.

The path is ISO_PACKAGE_CACHES, imported rather than repeated - the two
halves agreeing is the whole mechanism, and a second literal beside it is one
that drifts silently into a cache nothing reads.

Signatures are staged with the packages. pacman verifies a cached package
against its .sig exactly as it would a downloaded one; a cache holding only
the .pkg.tar.zst re-downloads every file with "failed to retrieve", which is
the entire saving lost to a missing copy. Verified both ways.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The resolver the installer package used to run at its own build time.
# Imported rather than reimplemented: it already parses the same two lists
# this file does, and a second copy of that parsing is one that drifts.
sys.path.insert(0, str(ROOT / "installer"))
from expected_package_count import (  # noqa: E402
    configurator_packages,
    count,
    desktop_packages,
)

# What archinstall itself straps during an install, beyond the lists it is
# handed, that the live medium does not already carry. setup_swap() straps
# zram-generator, and the configurator enables swap; everything else it can
# strap - sudo, linux-firmware, mkinitcpio, the microcode, efibootmgr,
# lvm2, libfido2, iwd - is installed on the medium and reaches the target
# through the live copy. Checked against archinstall 4.4's pacman.strap()
# calls and the 2026.09.26 ISO.
ARCHINSTALL_EXTRAS = ("zram-generator",)


def cache_path() -> Path:
    """Where the installer looks, read from the installer itself.

    Parsed rather than imported: phases_impl imports archinstall at module
    scope, which is not installed in the ISO build container.
    """
    source = (ROOT / "installer" / "orchestrator" / "phases_impl.py").read_text()
    match = re.search(r"^ISO_PACKAGE_CACHES\s*=\s*\(([^)]*\)[^)]*)\)", source, re.MULTILINE)
    if not match:
        raise SystemExit("seed_install_cache: ISO_PACKAGE_CACHES not found in phases_impl.py")
    paths = re.findall(r"""Path\(["']([^"']+)["']\)""", match.group(1))
    if not paths:
        raise SystemExit("seed_install_cache: ISO_PACKAGE_CACHES names no path")
    # the first is the one the installer lists first, so it is the one a
    # cache hit comes from
    return Path(paths[0])


def requested_packages() -> list[str]:
    """Every name an install asks pacman for, from every list it reads.

    One function, so the staging here and check_iso_packages.py's check of
    it read the same set: the check built its own and, missing the
    configurator's list the same way, passed an ISO that could not install
    offline (#101).
    """
    return sorted({
        "base",
        *iso_packages(),
        *configurator_packages(),
        *desktop_packages(),
        *ARCHINSTALL_EXTRAS,
    })


def iso_packages() -> list[str]:
    """What the live ISO itself installs.

    These are the packages the install is most wasteful about: they are on
    the medium already, and seven of them - firefox among them - are
    requested again from the network during the install.

    A `repo/name` line pins a package to a repository for resolution; the
    cache only needs the name.
    """
    listing = (ROOT / "iso" / "packages.x86_64").read_text()
    names = []
    for raw in listing.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line.rsplit("/", 1)[-1])
    return names


def download(packages: list[str], cache: Path, pacman_conf: Path) -> None:
    """Populate `cache` with `packages` AND their whole dependency closure.

    With dependencies, deliberately. This used to pass --nodeps twice and
    stage only the named packages, which made the cache a bandwidth
    optimisation rather than a source: 139 names against a 719-package
    closure, so 594 of the packages an install needs - glibc, alsa-lib,
    accountsservice - were never on the medium and every install was bound
    to the network whatever the cache held.

    The closure is what makes an offline install possible at all, and that
    is now the point of the ISO rather than a saving on top of it. It costs
    what #82 measured it would: ~1.1 GiB of packages, most of which is a
    second copy of files already unpacked in the same squashfs, and an ISO
    around 3.1 GB rather than 2.0.

    Retried, because this fetches over a gigabyte from mirrors and one slow
    file fails the whole transaction: build-iso failed twice in a row here,
    on 'speexdsp ... Operation too slow' from mirror.cachyos.org and on a
    file that vanished mid-publish. --disable-download-timeout relaxes the
    first; a retry covers the rest, and already-fetched files stay in the
    cache so an attempt resumes rather than restarts.

    --noconfirm is doing more than suppressing a prompt. Resolving the
    closure asks which provider to take sixteen times - gawk, ncurses,
    iptables, jack and the rest exist in both a v3 repository and core or
    extra - and --noconfirm takes the default, which is the first
    repository listed. That is the same rule the install itself resolves
    by, so the cache holds the v3 build the target would have fetched
    (verified: gawk staged as gawk-5.4.1-1.1-x86_64_v3). Reordering the
    repositories in iso/pacman.conf would silently change what is cached.
    """
    cache.mkdir(parents=True, exist_ok=True)
    dbpath = cache.parent / "db"
    dbpath.mkdir(parents=True, exist_ok=True)

    common = [
        "--config", str(pacman_conf),
        "--dbpath", str(dbpath),
        "--noconfirm",
        "--disable-download-timeout",
    ]
    subprocess.run(["pacman", "-Sy", *common], check=True)

    attempts = 3
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            ["pacman", "-Sw", *common, "--cachedir", str(cache), *packages],
            check=False,
        )
        if result.returncode == 0:
            return
        if attempt == attempts:
            raise subprocess.CalledProcessError(result.returncode, result.args)
        # -Sy again: a failure can be a package that was republished under a
        # new version while this ran, and the stale database would keep
        # asking for the name that no longer exists.
        print(f"  download failed ({attempt}/{attempts}); resyncing and retrying")
        subprocess.run(["pacman", "-Sy", *common], check=True)


def live_closure(dbpath: Path, pacman_conf: Path) -> set[str]:
    """Every package the live medium will have unpacked, names only.

    Resolved rather than read off the rootfs. This runs BEFORE mkarchiso
    pacstraps - `iso/airootfs` is the profile, and it carries no pacman
    database at all - so there is nothing to read yet. Asking pacman what
    iso/packages.x86_64 resolves to gives the same answer the build will
    reach, because it is the same question against the same databases.

    The list names 91 packages; the closure behind them is 505, and it is
    the closure that ends up on the medium.
    """
    result = subprocess.run(
        [
            "pacman", "-Sp", "--print-format", "%n",
            "--config", str(pacman_conf),
            "--dbpath", str(dbpath),
            *iso_packages(),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def prune_already_installed(cache: Path, installed: set[str]) -> int:
    """Delete cached tarballs for packages the medium already carries.

    The signature goes with the package: pacman verifies one against the
    other, and a .sig with no .pkg beside it is a file nobody reads.
    """
    removed = 0
    for package in sorted(cache.glob("*.pkg.tar.*")):
        if package.suffix == ".sig":
            continue
        name = package.name.rsplit("-", 3)[0]
        if name not in installed:
            continue
        signature = package.with_name(package.name + ".sig")
        package.unlink()
        signature.unlink(missing_ok=True)
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rootfs", type=Path, required=True,
        help="the airootfs mkarchiso is assembling",
    )
    parser.add_argument(
        "--pacman-conf", type=Path, default=ROOT / "iso" / "pacman.conf",
        help="the configuration to resolve against, v3 repositories and all",
    )
    args = parser.parse_args()

    # Every list the install asks for, read from where the installer keeps
    # it. `base` explicitly: minimal_installation() pacstraps it and it
    # appears in none of them. The configurator's packages were missing
    # until 2026-09-26 - base-devel, chwd, the ashlaros-* set and
    # ashlaros-settings, which phases_impl installs with DESKTOP_PACKAGES
    # and which pull 141 packages the cache did not hold. An install with no
    # network failed at its first package transaction, and nothing ran one
    # to notice (#101).
    packages = requested_packages()
    cache = args.rootfs / cache_path().relative_to("/")

    print(f"staging {len(packages)} requested packages, with dependencies, into {cache}")
    download(packages, cache, args.pacman_conf)

    # Drop what the medium already carries unpacked. The installer seeds
    # the target by copying the live root (livecopy.py), so a package
    # installed on the ISO does not need its tarball shipped beside it -
    # and 505 of the 695 were, at 1256 MiB, 37% of the image (#104).
    #
    # Pruned after the download rather than before it: pacman resolves the
    # closure, and asking it for a subset would drop dependencies the 190
    # genuinely need. Cheaper to fetch everything once at build time and
    # delete what the squashfs already has.
    installed = live_closure(cache.parent / "db", args.pacman_conf)
    if installed:
        pruned = prune_already_installed(cache, installed)
        print(f"pruned {pruned} packages the medium carries unpacked")
    else:
        print("could not resolve the live closure; staging everything")

    # The dashboard's denominator. Written here, onto the medium, rather
    # than into the installer package: it is resolved against live
    # repositories, so the same commit yields a different count on a
    # different day - and pkgrel is a commit count, so a rebuild cannot
    # move it. That combination made publish.py refuse the package as
    # "already published with different content" (53138 vs 53139 bytes),
    # which is a build-time property of the medium ending up versioned as
    # if it were source. The ISO is rebuilt every time, so it is the right
    # owner; `count` resolves against the databases staged just above.
    expected = args.rootfs / "usr/share/ashlaros-installer/expected-packages"
    expected.parent.mkdir(parents=True, exist_ok=True)
    try:
        total = count(args.pacman_conf, cache.parent / "db")
    except SystemExit as exc:
        # Not fatal, deliberately: without the file the dashboard falls
        # back to whole-phase arithmetic, which is what it did before #94.
        print(f"could not resolve the package count ({exc}); the bar moves per phase")
    else:
        expected.write_text(f"{total}\n")
        print(f"expected packages: {total} -> {expected}")

    staged = sorted(cache.glob("*.pkg.tar.*"))
    signatures = [path for path in staged if path.suffix == ".sig"]
    size = sum(path.stat().st_size for path in staged)
    print(
        f"staged {len(staged) - len(signatures)} packages, "
        f"{len(signatures)} signatures, {size / 1024 / 1024:.0f} MiB"
    )
    if not signatures:
        raise SystemExit(
            "seed_install_cache: no signatures staged; pacman would refetch everything"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
