#!/usr/bin/env python3
"""Every shell script in the tree, found by shebang rather than by name.

check.yml used to carry a hand-written list of paths. It drifted the way a
hand-written list does: eight shipped scripts were never checked, among them
`clipboard` and `taildrop-send`, and the omission was invisible because a
file nobody lists is a file nobody fails on. `termbin` and `termpaste` had
real SC2140 findings sitting in them the whole time.

Discovery instead. A file is a shell script if git tracks it and its first
line names sh, bash, dash or ksh - extension optional, since most of what
this repo ships has none.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SHELLS = ("sh", "bash", "dash", "ksh")


def is_shell(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            first = handle.readline(200)
    except OSError:
        return False
    if not first.startswith(b"#!"):
        return False
    line = first.decode("utf-8", "replace")
    # "#!/bin/sh", "#!/usr/bin/env bash", "#!/bin/bash -e"
    return any(line.split(maxsplit=2)[0].endswith(s) or f" {s}" in line for s in SHELLS)


def tracked() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [ROOT / name for name in out.split("\0") if name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--relative", action="store_true", help="print paths relative to the checkout"
    )
    args = parser.parse_args()

    found = sorted(p for p in tracked() if p.is_file() and is_shell(p))
    # A tree that suddenly has no shell scripts means the detection broke,
    # not that they were all deleted - and an empty argv makes shellcheck
    # exit 0, which would turn this check green forever.
    if len(found) < 20:
        raise SystemExit(
            f"shell_sources: found only {len(found)} shell scripts, which cannot "
            "be right - check the shebang detection rather than shipping a "
            "check that passes by finding nothing"
        )

    try:
        for path in found:
            print(path.relative_to(ROOT) if args.relative else path)
    except BrokenPipeError:
        # `shell_sources.py | head` is how anyone inspects this by hand, and
        # a traceback on a closed pipe reads as a broken script
        sys.stdout = None
    return 0


if __name__ == "__main__":
    sys.exit(main())
