#!/usr/bin/env python3
"""Take packages that no longer have a PKGBUILD out of the published repository.

publish.py only ever adds: it extends the live database with repo-add and
prunes older versions of what it just published. A package whose PKGBUILD
is deleted is never published again, so nothing prunes it - its entry and
its files stay in both trees for good, installable by name. Measured
2026-09-26, nine names sat in each database with no PKGBUILD behind them,
among them swaylock-effects, which provides and conflicts with swaylock:
`pacman -S swaylock-effects` still swapped out the lock screen for a fork
two releases behind.

This compares each live database against every pkgname the tree's
PKGBUILDs produce, and removes what is left over. The order is
publish.py's, for the same reason: the database first, so a client never
fetches an entry whose file is gone, then the files, which nothing names
any more.

It refuses rather than guesses:

  - A dry run unless --apply is given, printing exactly what would go.
  - More than MAX_REMOVALS at once is refused. A pkgname the parser read
    wrong, or a checkout with packages/ missing, would otherwise look like
    "everything was dropped" and empty the repository.
  - A dropped package that a published one still depends on is refused, and
    so is the whole run: removing it breaks every install of the dependent.
    The fix for that is in the tree - drop the dependency first.

A dependency is only a reason to keep a package when this repository is
what satisfies it. swaylock-effects provides swaylock, which
ashlaros-settings depends on, and so does extra's swaylock; xdg-terminal-
exec is in extra on both architectures now. Removing ours changes which
package pacman picks, not whether one exists - so a dependency another
repository in the machine's stack also offers does not hold a removal up.
The distribution databases are read, not assumed: Arch's for x86_64 and
Arch Linux ARM's for aarch64, as the machines on each actually see them.
"""

import argparse
import os
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from publish import DB_NAME, PKG_SUFFIXES, download_databases, upload_databases
from r2 import log, s3_client

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"

# The repositories a machine on each architecture resolves from besides
# ours. CachyOS is x86_64-only and carries nothing an aarch64 machine could
# see; for x86_64, Arch's own is the floor every CachyOS install also has.
DISTRO = {
    "x86_64": [f"https://geo.mirror.pkgbuild.com/{r}/os/x86_64/{r}.db" for r in ("core", "extra")],
    "aarch64": [f"http://mirror.archlinuxarm.org/aarch64/{r}/{r}.db"
                for r in ("core", "extra", "alarm")],
}

# Five dropped packages per tree is what a normal drop looks like; nine was
# a year of backlog. Twice that is not a drop, it is a broken read.
MAX_REMOVALS = 20


def produced() -> set[str]:
    """Every pkgname a PKGBUILD in the tree builds, as makepkg reads it.

    Sourced, not parsed: pkgname can be an array, an indirection through
    ${_pkgname}, or a split package, and a regex that misreads one of those
    here does not rebuild something needlessly - it deletes it. A PKGBUILD
    that fails to source is fatal for the same reason.
    """
    names: set[str] = set()
    read = 'cd "$1" && source ./PKGBUILD >/dev/null && printf "%s\\n" "${pkgname[@]}"'
    for pkgbuild in sorted(PACKAGES.glob("*/PKGBUILD")):
        out = subprocess.run(
            ["bash", "-c", read, "_", str(pkgbuild.parent)], capture_output=True, text=True
        )
        found = out.stdout.split()
        if out.returncode != 0 or not found:
            raise SystemExit(f"{pkgbuild}: could not read its pkgname; refusing to remove anything")
        names.update(found)
    return names


def entries(db_path: str, strict: bool = True) -> dict[str, dict[str, list[str]]]:
    """{pkgname: {FIELD: [values]}} for every entry in a database.

    strict for ours, where an entry that cannot be read is an entry this
    cannot account for - so nothing is removed. Not for a distribution's:
    Arch Linux ARM's extra carries a findnewest entry whose desc is 1271
    zero bytes at the source, and one unreadable name there only means
    one fewer name offered elsewhere.
    """
    out: dict[str, dict[str, list[str]]] = {}
    with tarfile.open(db_path) as archive:
        for member in archive:
            if not member.name.endswith("/desc"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            fields: dict[str, list[str]] = {}
            for block in handle.read().decode("utf-8", "replace").strip().split("\n\n"):
                lines = block.split("\n")
                if lines and lines[0].startswith("%"):
                    fields[lines[0].strip("%")] = lines[1:]
            if "NAME" not in fields:
                if strict:
                    raise SystemExit(f"{db_path}: {member.name} cannot be read; refusing")
                continue
            out[fields["NAME"][0]] = fields
    return out


def bare(dependency: str) -> str:
    """A depends entry without its version constraint: foo>=1.2 -> foo."""
    for op in (">=", "<=", "=", ">", "<"):
        dependency = dependency.split(op, 1)[0]
    return dependency


def offered(db_paths: list[str]) -> set[str]:
    """Every name another repository satisfies: its packages and their provides."""
    names: set[str] = set()
    for path in db_paths:
        for name, fields in entries(path, strict=False).items():
            names.add(name)
            names |= {bare(p) for p in fields.get("PROVIDES", [])}
    return names


def plan(live: dict[str, dict[str, list[str]]], wanted: set[str],
         elsewhere: set[str]) -> tuple[list[str], list[str]]:
    """(dropped, refusals) for one database.

    elsewhere is every name the distribution's repositories satisfy; a
    dependency on one of those is not one only this repository can meet.
    """
    dropped = sorted(set(live) - wanted)
    kept = {name: fields for name, fields in live.items() if name not in dropped}
    refusals = []
    for name in dropped:
        # a kept package can reach a dropped one by name or through what it provides
        offers = {name} | {bare(p) for p in live[name].get("PROVIDES", [])}
        for other, fields in sorted(kept.items()):
            needs = {bare(d) for d in fields.get("DEPENDS", [])} & offers
            if needs - elsewhere:
                refusals.append(f"{other} still depends on {name}, and no other repository "
                                f"offers {', '.join(sorted(needs - elsewhere))}")
    if len(dropped) > MAX_REMOVALS:
        refusals.append(f"{len(dropped)} packages to remove, more than {MAX_REMOVALS}: "
                        "that is a broken read of the tree, not a drop")
    return dropped, refusals


def distro_databases(arch: str, workdir: str) -> list[str]:
    """The distribution's databases for arch, fetched into workdir."""
    paths = []
    for url in DISTRO[arch]:
        path = os.path.join(workdir, "distro-" + url.rsplit("/", 1)[1])
        # a failed fetch is fatal: an empty "elsewhere" would only make this
        # refuse more, but a partial one could let a real dependency through
        urllib.request.urlretrieve(url, path)
        paths.append(path)
    return paths


def remove(s3, bucket: str, arch: str, workdir: str, wanted: set[str], key: str | None,
           apply: bool) -> bool:
    prefix = f"{arch}/"
    os.makedirs(workdir, exist_ok=True)
    elsewhere = offered(distro_databases(arch, workdir))
    download_databases(s3, bucket, prefix, workdir)
    db_file = os.path.join(workdir, f"{DB_NAME}.db.tar.gz")
    if not os.path.exists(db_file):
        log(f"{arch}: no database; nothing to remove")
        return True

    live = entries(db_file)
    dropped, refusals = plan(live, wanted, elsewhere)
    if refusals:
        for refusal in refusals:
            log(f"{arch}: refusing: {refusal}")
        return False
    if not dropped:
        log(f"{arch}: every published package has a PKGBUILD")
        return True

    files = {name: live[name]["FILENAME"][0] for name in dropped}
    for name in dropped:
        log(f"{arch}: {'removing' if apply else 'would remove'} {name} ({files[name]})")
    if not apply:
        return True

    repo_remove = ["repo-remove", db_file, *dropped]
    if key:
        repo_remove[1:1] = ["--sign", "--key", key]
    subprocess.run(repo_remove, check=True)
    # the database first: once it no longer names them, the files are
    # unreachable and deleting them is unobservable
    upload_databases(s3, bucket, arch, workdir)

    doomed = set(files.values())
    doomed |= {f"{f}.sig" for f in doomed}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            name = obj["Key"].removeprefix(prefix)
            if name in doomed and name.removesuffix(".sig").endswith(PKG_SUFFIXES):
                s3.delete_object(Bucket=bucket, Key=obj["Key"])
                log(f"{arch}: deleted {name}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true",
                        help="remove them; without it, only print what would go")
    parser.add_argument("--workdir", default="removed", help="where the databases are rewritten")
    args = parser.parse_args()

    wanted = produced()
    bucket = os.environ["R2_BUCKET"]
    key = os.environ.get("GPG_KEYID")
    s3 = s3_client()

    ok = True
    for arch in ("x86_64", "aarch64"):
        ok &= remove(s3, bucket, arch, os.path.join(args.workdir, arch), wanted, key, args.apply)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
