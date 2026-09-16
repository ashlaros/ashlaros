#!/usr/bin/env python3
"""Find published packages whose libraries no longer exist.

A package built against one version of a library keeps the soname it linked
against - `libinput.so.10`, `libwlroots-0.19.so`. When the distribution moves
that soname, our package is left naming a file nothing provides any more: it
installs, because pacman resolves the plain package names our PKGBUILDs
declare, and then fails to start. Nothing in the build pipeline notices,
because nothing in the package directory changed.

So the question is asked of the published artefacts rather than of the
sources: for every ELF file a package ships, does every DT_NEEDED entry still
resolve to a package in the configured repositories?

Resolution is `pacman -F`, which searches the file lists of the repositories
as they are *today*. A soname no package owns is the breakage this exists to
find. Sonames the dynamic loader supplies itself - ld-linux, linux-vdso - are
owned by no package by design and are not breakage.

Packages are downloaded and unpacked, never installed: installing pulls the
dependency tree of every package under test, which on this set is most of a
desktop, and says nothing extra. `pacman -Sw` plus `tar` is the whole need.

Prints the package names that need rebuilding, one per line, on stdout; the
reasoning goes to stderr. Exit 0 when everything resolves, 1 when something
does not, 2 when the audit could not run.
"""

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# The dynamic loader provides these; no package owns them, and a lookup would
# report every binary in the repository as broken.
LOADER_PROVIDED = ("linux-vdso.so", "ld-linux", "ld.so")

ELF_MAGIC = b"\x7fELF"


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def repo_packages(repo: str) -> list[str]:
    """Every package name the repository publishes for this architecture.

    Debug packages are excluded. makepkg splits them out of the same build,
    they ship unstripped ELF whose DT_NEEDED mirrors the real package's, and
    a rebuild is driven by the package that is actually installed.
    """
    result = run("pacman", "-Slq", repo)
    if result.returncode != 0:
        raise SystemExit(f"cannot list {repo}: {result.stderr.strip()}")
    return sorted(
        name
        for name in result.stdout.split()
        if name and not name.endswith("-debug")
    )


def needed_sonames(path: Path) -> list[str]:
    """The DT_NEEDED entries of one ELF file."""
    result = run("readelf", "-d", str(path))
    if result.returncode != 0:
        return []
    sonames = []
    for line in result.stdout.splitlines():
        if "(NEEDED)" not in line:
            continue
        # ` 0x0001 (NEEDED)  Shared library: [libc.so.6]`
        start = line.rfind("[")
        end = line.rfind("]")
        if start != -1 and end > start:
            sonames.append(line[start + 1 : end])
    return sonames


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == ELF_MAGIC
    except OSError:
        return False


def provider_of(soname: str, cache: dict[str, str | None]) -> str | None:
    """The package owning a soname, or None when nothing does.

    `pacman -Fq` prints `repo/pkgname`, NOT the matched path - so a filter
    looking for a line ending in the soname matches nothing and reports every
    library in the distribution as missing. Its exit status is 0 whether or
    not anything matched, too, which is why emptiness is what decides here.
    """
    if soname in cache:
        return cache[soname]
    # Anchored to usr/lib/: a bare soname is a substring search, and
    # `libc.so.6` alone also matches lib32-glibc and the cross-compiler's
    # aarch64-linux-gnu-glibc - neither of which provides the library an
    # x86_64 binary on this machine loads.
    result = run("pacman", "-Fq", f"usr/lib/{soname}")
    owner = next((line.strip() for line in result.stdout.splitlines() if line.strip()), None)
    cache[soname] = owner
    return owner


def unpack(archive: Path, into: Path) -> None:
    """Extract only the regular files, into `into`.

    Regular files alone, because only they can be ELF: a symlink points at
    something already extracted or outside the package, and reading its
    target says nothing about what was linked. Skipping them also sidesteps
    the reason a whole-archive extract fails here - zen-browser-bin ships
    `opt/zen-browser-bin/dictionaries` as a link to an absolute path, which
    data_filter rejects with AbsoluteLinkError, aborting the extraction and
    with it the audit of every package after it.

    Members are still filtered rather than trusted: a package is a tar
    fetched over the network, and `data` is what keeps it inside `into`.
    """
    with tarfile.open(archive) as tar:
        for member in tar:
            if member.isfile():
                tar.extract(member, into, filter="data")


def audit(packages: list[str], workdir: Path) -> dict[str, list[tuple[str, str]]]:
    """{package: [(file, unresolvable soname)]} for everything that broke."""
    download = workdir / "dl"
    download.mkdir(parents=True, exist_ok=True)
    # pacman drops privileges to an unprivileged user to download, so both
    # the cache directory AND every directory above it have to be reachable
    # by that user. mkdtemp makes its directory 0700 root, which fails every
    # fetch with "Permission denied" on a .part file - a message that names
    # neither the permission nor the directory actually at fault. Measured:
    # parent 0700 downloads nothing, parent 0755 downloads everything.
    workdir.chmod(0o755)
    download.chmod(0o777)

    # --nodeps twice, not once. The first relaxes version constraints; only
    # the second stops pacman resolving the dependency tree, and the
    # difference is not academic - measured on way-displays, one --nodeps
    # fetches 10 packages and two fetch 1. The tree comes from Arch and is
    # current by definition, so downloading it is a desktop's worth of
    # transfer to audit files we did not build.
    result = run(
        "pacman", "-Sw", "--noconfirm", "--nodeps", "--nodeps",
        "--cachedir", str(download), *packages,
    )
    if result.returncode != 0:
        raise SystemExit(f"could not download packages: {result.stderr.strip()}")

    cache: dict[str, str | None] = {}
    broken: dict[str, list[tuple[str, str]]] = {}
    extracted = workdir / "x"

    for package in packages:
        archives = sorted(download.glob(f"{package}-*.pkg.tar.*"))
        archives = [a for a in archives if not a.name.endswith(".sig")]
        # `-Sw` also caches the dependencies it resolved, and a glob on a
        # short name matches longer ones: `mise-bin-*` would not catch
        # `mise-bin`'s own file if another package shared the prefix. Keep
        # only archives whose name is this package at some version.
        archives = [a for a in archives if a.name[: len(package) + 1] == f"{package}-"]
        if not archives:
            log(f"{package}: nothing downloaded, skipping")
            continue

        if extracted.exists():
            shutil.rmtree(extracted)
        extracted.mkdir(parents=True)
        unpack(archives[-1], extracted)

        # A package that ships its own libraries satisfies their sonames
        # itself, through RPATH or a wrapper setting LD_LIBRARY_PATH.
        # zen-browser-bin is the whole reason this set exists: it bundles
        # libmozsqlite3.so, libgkcodecs.so and nine more beside libxul.so
        # under opt/, and no package in any repository provides them -
        # correctly, because none should.
        bundled = {
            path.name
            for path in extracted.rglob("*")
            if path.is_file() and not path.is_symlink()
        }

        for path in sorted(extracted.rglob("*")):
            if not path.is_file() or path.is_symlink() or not is_elf(path):
                continue
            for soname in needed_sonames(path):
                if soname.startswith(LOADER_PROVIDED) or soname in bundled:
                    continue
                if provider_of(soname, cache) is None:
                    shipped = str(path.relative_to(extracted))
                    broken.setdefault(package, []).append((shipped, soname))

    return broken


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="ashlaros", help="repository to audit")
    parser.add_argument(
        "package", nargs="*", help="audit these rather than the whole repository"
    )
    args = parser.parse_args()

    if not shutil.which("readelf"):
        log("readelf is missing; install binutils")
        return 2

    # the file lists this resolves sonames against have to be current, or a
    # library that moved yesterday still looks present
    if run("pacman", "-Fy").returncode != 0:
        log("could not refresh the file databases")
        return 2

    packages = args.package or repo_packages(args.repo)
    log(f"auditing {len(packages)} package(s)")

    with tempfile.TemporaryDirectory() as workdir:
        broken = audit(packages, Path(workdir))

    if not broken:
        log("every soname still resolves")
        return 0

    for package, failures in sorted(broken.items()):
        for shipped, soname in failures:
            log(f"{package}: {shipped} needs {soname}, which no package provides")
        print(package)
    return 1


if __name__ == "__main__":
    sys.exit(main())
