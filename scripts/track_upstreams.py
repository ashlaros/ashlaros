#!/usr/bin/env python3
"""Report, and optionally apply, AUR changes to the PKGBUILDs vendored here.

The AUR is not a build input: an AUR PKGBUILD can be force-pushed between
two builds of the same version, so ours are copies. That makes them frozen
unless something looks, which is what this does.

Five of the vendored PKGBUILDs carry deliberate local edits - `arch=`
widened to aarch64, wluma's broken man-page step removed - so an update is
never a blind overwrite. `packages/.upstream/<name>.PKGBUILD` holds the
pristine upstream text each copy was made from, and that file is the merge
base: with it, an upstream change to a line we never touched applies
cleanly, and one to a line we did touch conflicts loudly. Without it the
"merge" is an overwrite that reverts our edits and reports success.

Exit status: 0 when nothing changed upstream, 1 when something did, 2 on
an error fetching. The workflow turns a 1 into a pull request; a human
decides whether our edits still apply.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ROOT / "packages"
MANIFEST = PACKAGES / "upstreams.yml"

AUR_PLAIN = "https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h={name}"


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def aur_name(upstream: str) -> str | None:
    """The AUR package a manifest `upstream` refers to, if it is an AUR one.

    Only aur.archlinux.org is fetched here. The manjaro-contrib upstreams
    are git repositories we mirror deliberately and rarely; treating them
    the same would mean cloning on every run for a diff that is almost
    always empty.
    """
    prefix = "https://aur.archlinux.org/"
    if not upstream.startswith(prefix):
        return None
    return upstream[len(prefix):].removesuffix(".git")


def fetch(name: str) -> bytes:
    request = urllib.request.Request(
        AUR_PLAIN.format(name=name),
        headers={"User-Agent": "ashlaros-track-upstreams"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    # cgit answers 200 with an HTML error page for an unknown package, so
    # a plausible-looking response still has to be checked
    if b"pkgname" not in body:
        raise ValueError(f"{name}: the AUR did not return a PKGBUILD")
    return body


def merge(base: bytes, ours: bytes, theirs: bytes) -> tuple[bytes, bool]:
    """Replay our local edits onto the new upstream text.

    `git merge-file` does the three-way merge, so a change upstream makes
    to a line we never touched applies cleanly, and one to a line we did
    touch conflicts loudly instead of silently reverting our edit.
    """
    with tempfile.TemporaryDirectory() as tmp:
        paths = {}
        for label, data in (("base", base), ("ours", ours), ("theirs", theirs)):
            paths[label] = Path(tmp, label)
            paths[label].write_bytes(data)

        result = subprocess.run(
            ["git", "merge-file", "-L", "ours", "-L", "vendored", "-L", "upstream",
             "-p", str(paths["ours"]), str(paths["base"]), str(paths["theirs"])],
            capture_output=True,
        )
        # exit >0 is the number of conflicts; <0 is an error
        return result.stdout, result.returncode == 0


def unified(old: bytes, new: bytes, name: str) -> str:
    import difflib

    return "".join(
        difflib.unified_diff(
            old.decode(errors="replace").splitlines(keepends=True),
            new.decode(errors="replace").splitlines(keepends=True),
            fromfile=f"{name}/PKGBUILD (upstream, as vendored)",
            tofile=f"{name}/PKGBUILD (upstream, now)",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the merged PKGBUILD and update the recorded hash",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="write a markdown summary here, for a pull request body",
    )
    parser.add_argument("--only", help="check a single package directory")
    args = parser.parse_args()

    manifest = yaml.safe_load(MANIFEST.read_text())
    packages = manifest["packages"]

    changed, conflicted, failed = [], [], []
    report = []

    for name in sorted(packages):
        if args.only and name != args.only:
            continue
        entry = packages[name] or {}
        upstream = entry.get("upstream")
        if not upstream:
            continue
        package = aur_name(upstream)
        if not package:
            continue

        pkgbuild = PACKAGES / name / "PKGBUILD"
        ours = pkgbuild.read_bytes()

        try:
            theirs = fetch(package)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            log(f"{name}: could not fetch upstream: {exc}")
            failed.append(name)
            continue

        base_path = PACKAGES / ".upstream" / f"{package}.PKGBUILD"
        if not base_path.exists():
            # without a base there is no three-way merge, and a two-way one
            # silently reverts our local edits
            log(f"{name}: no merge base at {base_path.relative_to(ROOT)}; skipping")
            failed.append(name)
            continue

        base = base_path.read_bytes()
        if sha256(base) == sha256(theirs):
            continue

        log(f"{name}: upstream changed")
        diff = unified(base, theirs, name)

        merged, clean = merge(base, ours, theirs)

        verdict = (
            "Merged cleanly."
            if clean
            else "**Conflicts** - our local edits overlap the upstream change."
        )
        report.append(f"### {name}\n\n{verdict}\n\n```diff\n{diff}```\n")

        if clean:
            changed.append(name)
            if args.apply:
                pkgbuild.write_bytes(merged)
                # base and vendored copy must always describe the same
                # upstream revision, or the next merge has the wrong base
                base_path.write_bytes(theirs)
        else:
            conflicted.append(name)

    if args.report and report:
        args.report.write_text(
            "The AUR moved under these vendored PKGBUILDs.\n\n"
            "Five of them carry deliberate local edits (`arch=` widened to\n"
            "aarch64, wluma's broken man-page step removed), so review that\n"
            "those survived before merging.\n\n" + "\n".join(report)
        )

    summary = {"changed": changed, "conflicted": conflicted, "failed": failed}
    print(json.dumps(summary))

    if failed:
        return 2
    return 1 if changed or conflicted else 0


if __name__ == "__main__":
    sys.exit(main())
