#!/usr/bin/env python3
"""Switch to the live session's VT and back, photographing both.

The session is on tty2 and the installer keeps tty1 (#83). The two things
worth proving are that sway actually comes up on the second VT rather than
leaving a black screen or a seat error, and that switching back finds the
installer still there - the regression that matters most, since a session
that disturbs the install is worse than no session.

Screenshots rather than assertions about pixels: a compositor that starts
and draws nothing looks identical to one that failed, and only a person
reading the picture can tell the difference. What this script does assert
is that the two screens differ, which catches the case where the VT switch
did nothing at all.
"""

import sys
import time
from pathlib import Path

from qmp import Qmp

OUT = Path("/vm/out")


def shoot(vm, name: str) -> Path:
    path = OUT / f"{name}.ppm"
    vm.cmd("screendump", filename=str(path))
    # screendump returns before the file is finished being written
    for _ in range(50):
        if path.exists() and path.stat().st_size:
            size = path.stat().st_size
            time.sleep(0.2)
            if path.stat().st_size == size:
                return path
        time.sleep(0.2)
    raise SystemExit(f"live-session: no screenshot at {path}")


def main() -> int:
    vm = Qmp()

    print("== on tty1, before the switch")
    before = shoot(vm, "live-tty1-before")

    vm.key("ctrl-alt-f2")
    # sway has to start from scratch here: agetty, zsh, .zlogin, then the
    # compositor bringing up an output. Generous, because a slow TCG run
    # takes far longer than a KVM one.
    time.sleep(45)
    session = shoot(vm, "live-tty2-session")

    vm.key("ctrl-alt-f1")
    time.sleep(5)
    after = shoot(vm, "live-tty1-after")

    sizes = {p.name: p.stat().st_size for p in (before, session, after)}
    for name, size in sizes.items():
        print(f"   {name}: {size} bytes")

    # A VT switch that did nothing leaves three identical frames. The
    # installer's own progress bar moves between the first and last, so
    # comparing those two proves nothing - the session frame is the one
    # that has to differ.
    if session.read_bytes() == before.read_bytes():
        print("live-session: tty2 is identical to tty1 - no switch happened")
        return 1

    print("== the live session VT differs from the installer's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
