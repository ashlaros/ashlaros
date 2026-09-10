#!/usr/bin/env python3
"""Decide what needs building, and in what order.

Three things shape a run:

  - `arch=any` packages build once and are registered in both databases;
    anything else builds per architecture. Read out of each PKGBUILD's own
    arch= line, so there is no second list to drift.

  - A package that depends on another package built here cannot be built in
    the same wave: the dependency has to be published before makepkg can
    resolve it. flashfocus needs python-xpybutil, and Arch packages neither.
    Wave 0 is everything with no such dependency; wave 1 is what depends on
    wave 0, and so on.

  - A package already published at the version its PKGBUILD declares is
    skipped. Rebuilding it is not free and not harmless: makepkg is not
    reproducible - two builds of one version differ in .BUILDINFO
    timestamps - so republishing replaces an object the worker serves as
    `immutable, max-age=31536000` and changes the %SHA256SUM% the database
    records for it. A client holding the cached old bytes then fails the
    checksum on install.

Skipping is by declared version AND source hash: the version alone would
miss a PKGBUILD edit that changes what gets built without touching pkgver
(wluma's dropped man-page step did exactly that, and needed pkgrel bumped
by hand). Set REBUILD_ALL=1 to ignore what is published and build
everything, which is what a toolchain change needs.

Writes GitHub Actions outputs on stdout.
"""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"

ARCH_RE = re.compile(r"^arch=\((.*?)\)", re.MULTILINE | re.DOTALL)
# depends and makedepends both have to exist before the build starts;
# optdepends do not, so they are deliberately absent here
DEPENDS_RE = re.compile(r"^(?:make)?depends=\((.*?)\)", re.MULTILINE | re.DOTALL)
PKGNAME_RE = re.compile(r"^pkgname=(.+)$", re.MULTILINE)
PKGVER_RE = re.compile(r"^pkgver=(.+)$", re.MULTILINE)
PKGREL_RE = re.compile(r"^pkgrel=(.+)$", re.MULTILINE)
EPOCH_RE = re.compile(r"^epoch=(.+)$", re.MULTILINE)
# a pinned revision makes a pkgver() deterministic
COMMIT_RE = re.compile(r"^_commit=[\"']?[0-9a-f]{40}", re.MULTILINE)

REPO_URL = os.environ.get("REPO_URL", "https://packages.ashlaros.download")
FIELD = re.compile(r"%([A-Z0-9]+)%\n([^\n]*)")

# What the repository records for a package we built, so a rebuild can be
# recognised as unnecessary. Not a pacman field - it goes in %PACKAGER%,
# which repo-add copies from the package and nothing else reads.
SOURCE_MARK = "ashlaros-src:"


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def field(pattern: re.Pattern, text: str) -> list[str]:
    """Every quoted or bare word in the first matching array assignment."""
    match = pattern.search(text)
    if not match:
        return []
    body = re.sub(r"#.*", "", match.group(1))
    return re.findall(r"[\w.+-]+", body.replace("'", " ").replace('"', " "))


def scalar(pattern: re.Pattern, text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip().strip("'\"") if match else None


def pkgname_of(pkgbuild: Path, text: str) -> str:
    """The package name a PKGBUILD produces.

    Three forms appear in ours: a plain `pkgname=swayr`, an array
    `pkgname=('nwg-wrapper')`, and an indirection `pkgname=${_pkgname}`.
    Reading the first as-is and the other two literally is what made the
    published-version lookup miss - the key was `${_pkgname}` and
    `('nwg-wrapper')`, so those two rebuilt on every run despite being
    unchanged.
    """
    raw = scalar(PKGNAME_RE, text)
    if not raw:
        return pkgbuild.parent.name

    # a shell variable: resolve it from its own assignment
    variable = re.fullmatch(r"\$\{?(\w+)\}?", raw)
    if variable:
        assigned = scalar(
            re.compile(rf"^{variable.group(1)}=(.+)$", re.MULTILINE), text
        )
        raw = assigned or pkgbuild.parent.name

    # an array of one, which is how some PKGBUILDs spell a single package
    words = re.findall(r"[\w.+@-]+", raw.replace("'", " ").replace('"', " "))
    return words[0] if words else pkgbuild.parent.name


def declared_version(text: str) -> str | None:
    """The version the PKGBUILD states, or None when it cannot be known here.

    A pkgver() function resolves the version from a source checkout at build
    time, which this cannot do. It is still knowable when the sources are
    pinned to a _commit: the checkout is then always the same one, so the
    version it computes is fixed, and the pkgver= line already carries the
    result. An unpinned pkgver() - a package tracking a branch tip - is
    genuinely unknowable and never skipped.
    """
    if "pkgver()" in text and not COMMIT_RE.search(text):
        return None
    pkgver = scalar(PKGVER_RE, text)
    pkgrel = scalar(PKGREL_RE, text)
    if not pkgver or not pkgrel:
        return None
    epoch = scalar(EPOCH_RE, text)
    return f"{epoch}:{pkgver}-{pkgrel}" if epoch else f"{pkgver}-{pkgrel}"


def authored_version(directory: Path) -> str | None:
    """The version a package we author will be built with.

    build-package.sh stamps this into the PKGBUILD from the package's git
    history, so the PKGBUILD on disk still carries the previous one. Asking
    the same question here is what keeps the skip honest: without it a
    payload edit would compare the OLD version against the published OLD
    version, match, and skip the very rebuild that edit needs.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "package_version.py"), str(directory)],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


SOURCE_TREES_RE = re.compile(r"^_source_trees=\((.*?)\)", re.MULTILINE | re.DOTALL)


def source_trees(directory: Path) -> list[Path]:
    """Directories a package is built from, itself first.

    ashlaros-installer builds from installer/ and ashlaros-branding from
    branding/, both outside their package directory. A PKGBUILD says so
    with _source_trees=(...); without it an edit there would change what
    the package ships while looking untouched, so the package would keep
    its version and be skipped forever.
    """
    trees = [directory]
    declared = SOURCE_TREES_RE.search((directory / "PKGBUILD").read_text())
    if declared:
        for name in declared.group(1).split():
            tree = ROOT / name.strip("\"'")
            if not tree.is_dir():
                raise SystemExit(
                    f"{directory.name}: _source_trees names {name}, which does not exist"
                )
            trees.append(tree)
    return trees


def source_hash(directory: Path) -> str:
    """A digest of everything a package is built from.

    The PKGBUILD alone is not enough: ashlaros-browser-settings ships five
    payload files beside it, and editing one changes the package without
    touching pkgver.
    """
    digest = hashlib.sha256()
    for tree in source_trees(directory):
        for path in sorted(p for p in tree.rglob("*") if p.is_file()):
            digest.update(path.relative_to(tree).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def published(arch: str) -> dict[str, tuple[str, str | None]]:
    """{pkgname: (version, source hash)} from the live database.

    A repository that cannot be reached yields nothing, so a run builds
    everything rather than skipping on incomplete information.
    """
    url = f"{REPO_URL}/{arch}/ashlaros.db.tar.gz"
    # a named User-Agent, because cloudflare's bot protection answers 403 to
    # urllib's default and a 403 here silently means "rebuild everything"
    request = urllib.request.Request(
        url, headers={"User-Agent": "ashlaros-discover-packages"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        log(f"{arch}: could not read the published database ({exc}); building everything")
        return {}

    entries = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.name.endswith("/desc"):
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            desc = dict(FIELD.findall(handle.read().decode()))
            name, version = desc.get("NAME"), desc.get("VERSION")
            if not name or not version:
                continue
            packager = desc.get("PACKAGER", "")
            mark = None
            if SOURCE_MARK in packager:
                mark = packager.split(SOURCE_MARK, 1)[1].strip().rstrip(">")
            entries[name] = (version, mark)
    return entries


def main() -> int:
    only = os.environ.get("ONLY", "").strip()
    rebuild_all = os.environ.get("REBUILD_ALL", "").strip() not in ("", "0", "false")

    packages = {}
    for pkgbuild in sorted(PACKAGES.glob("*/PKGBUILD")):
        text = pkgbuild.read_text()
        name = pkgbuild.parent.name
        packages[name] = {
            "pkgname": pkgname_of(pkgbuild, text),
            "any": field(ARCH_RE, text) == ["any"],
            "depends": field(DEPENDS_RE, text),
            "version": authored_version(pkgbuild.parent) or declared_version(text),
            "source": source_hash(pkgbuild.parent),
        }

    if only:
        if only not in packages:
            raise SystemExit(f"no package directory named {only}")
        packages = {only: packages[only]}

    skipped = []
    if not rebuild_all and not only:
        # an `any` package lives in both trees, so it counts as built only
        # when both carry it; a compiled one is judged per architecture in
        # its own leg, and x86_64 is the one the ISO is built from
        live = {arch: published(arch) for arch in ("x86_64", "aarch64")}
        for name, meta in list(packages.items()):
            version, source = meta["version"], meta["source"]
            if version is None:
                continue
            arches = ("x86_64", "aarch64") if meta["any"] else ("x86_64",)
            if all(live[a].get(meta["pkgname"]) == (version, source) for a in arches):
                skipped.append(name)
                del packages[name]

    provided = {meta["pkgname"]: name for name, meta in packages.items()}

    waves = []
    remaining = dict(packages)
    built: set[str] = set()
    while remaining:
        ready = {
            name: meta
            for name, meta in remaining.items()
            # only dependencies we build in THIS run can hold a package
            # back; anything skipped is already published, and anything
            # else comes from Arch or CachyOS
            if not {
                provided[d] for d in meta["depends"] if d in provided and provided[d] != name
            }
            - built
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
        built |= {m["pkgname"] for m in ready.values()}
        for name in ready:
            del remaining[name]

    if skipped:
        log(f"already published, not rebuilding: {', '.join(sorted(skipped))}")

    print(f"waves={json.dumps(waves)}")
    print(f"wave_count={len(waves)}")
    print(f"skipped={json.dumps(sorted(skipped))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
