"""Drive the installer from its first screen to a rebooted system.

The promise the installer makes is that Enter through every screen
installs, so that is what this sends - except the two password fields,
which have no default by design (the user password is also the LUKS
passphrase).

It takes the offered reboot rather than being killed at the prompt.
SIGKILLing qemu there loses the ESP to the qcow2 writeback cache and the
next boot reports `Volume corrupt`, which looks like a bootloader bug and
is not one.
"""

import os
import sys
import time

sys.path.insert(0, "/vm")
from qmp import Qmp

PASSWORD = "correcthorse"

# gum's selected-button background as the framebuffer renders it, measured
# off a real completion screen - not the 24-bit value the theme names.
#
# The run length is the whole difference between a button and a text
# cursor, which is the same colour. Measured across every screen the
# driver visits: a cursor is exactly 8 pixels - one glyph cell - and the
# hostname, disk and password screens all carry one. "Reboot now" is ten
# characters, so the real button is ~96 wide; 32 sits well clear of a
# cursor and well under the button.
#
# At 8 this matched the password field's cursor and reported a finished
# install four minutes in, on a run that had not started installing.
SELECTED = bytes([0xAA, 0x00, 0xAA]) * 32


def _same(a, b, tolerance=2000):
    """Whether two framebuffer dumps show the same thing.

    A blinking cursor rewrites a handful of pixels every frame, which is
    enough to make two dumps of an identical screen compare unequal. The
    PPMs are ~3 MB, so a few thousand differing bytes is a cursor and
    anything larger is the screen actually doing something.
    """
    if len(a) != len(b):
        return False
    return sum(x != y for x, y in zip(a, b, strict=True)) <= tolerance


def finished(path):
    """Whether the dashboard is showing its final Reboot? prompt.

    The screenshot is a framebuffer dump, so there is no text to match;
    the prompt is the only screen that draws a selected button.
    """
    try:
        with open(path, "rb") as handle:
            return SELECTED in handle.read()
    except OSError:
        return False


def screen(q, name="probe"):
    """What is on the framebuffer now."""
    with open(q.shot(name), "rb") as handle:
        return handle.read()


def advance(q, before, timeout=120):
    """Wait for the screen to change from `before` and then stop moving.

    The driver used to sleep a fixed four seconds between keystrokes. That
    is a guess about how long a TUI takes to redraw, and when it is wrong
    the keystrokes do not stop arriving - they go to whatever screen is
    actually up. A run that guessed wrong typed the password into the
    username field, which then sat on screen 2 for an hour while the
    sampling loop waited for an install that had never started.

    Waiting on the picture instead makes the driver as fast as the guest
    and as slow as it needs to be, which is the same property the boot
    wait already has.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        time.sleep(1)
        now = screen(q)
        if now != before and now == last:
            return now
        last = now
    raise SystemExit("the screen never settled after a keystroke")


def main():
    q = Qmp()

    # screen 1: locale & keyboard, EU default preselected
    q.shot("step-1-locale")
    here = screen(q)
    q.key("ret")
    here = advance(q, here)

    # screen 2: user. The username has a default, the passwords do not.
    q.shot("step-2-user")
    q.key("ret")
    here = advance(q, here)
    q.type(PASSWORD)
    q.key("ret")
    here = advance(q, here)
    q.type(PASSWORD)
    q.key("ret")
    here = advance(q, here)
    q.shot("step-2-hostname")
    q.key("ret")
    here = advance(q, here)
    q.key("ret")
    here = advance(q, here)

    # screen 3: encryption, on by default
    q.shot("step-3-encryption")
    q.key("ret")
    here = advance(q, here)

    # screen 3b: how the disk unlocks. First entry - passphrase only - is
    # what Enter takes, and it is the one mode that asks nothing further:
    # the two TPM modes would open a PIN field this driver has no answer
    # for. Installing with a TPM is covered by the settings TUI, not here.
    q.shot("step-3b-unlock")
    q.key("ret")
    here = advance(q, here)

    # screen 4: layout, erase disk + btrfs by default
    q.shot("step-4-disk")
    q.key("ret")
    here = advance(q, here)
    q.key("ret")
    advance(q, here)

    q.shot("step-5-confirm")
    q.key("ret")

    # then the dashboard runs. Sample it until the prompt appears; under
    # TCG the install takes roughly 35 minutes, with KVM about five.
    #
    # Each sample is announced. Without it a slow run and a stuck one look
    # identical from outside - a CI step that has printed nothing for forty
    # minutes says only that it has printed nothing - and the sampling is
    # the one place that knows the install is still being watched.
    #
    # A dashboard that is installing repaints - a package name, a counter, a
    # progress bar. One that is waiting on a prompt this driver did not
    # answer is a still picture, and it stays one until the loop gives up.
    # That is how adding "How should this disk unlock?" to the configurator
    # turned a 13-minute job into a 92-minute one that reported nothing
    # useful: the driver was in step with a screen sequence that had moved.
    #
    # How long a still screen is allowed to last depends on the accelerator.
    # Step 2 pulls the package set, and the dashboard repaints per step, not
    # per package: with KVM that download is a couple of minutes, but under
    # TCG it ran past seven and a half and tripped this detector on an
    # install that was working fine. The guest is the same either way, so
    # the bound scales with the thing that actually changed.
    kvm = os.access("/dev/kvm", os.R_OK | os.W_OK)
    stuck_limit = 10 if kvm else 40
    last = None
    unchanged = 0
    for i in range(120):
        time.sleep(45)
        path = q.shot(f"install-{i:02d}")
        print(f"sample {i:02d} at {(i + 1) * 45}s", flush=True)
        if finished(path):
            time.sleep(5)
            q.key("ret")
            print("rebooting", flush=True)
            return
        with open(path, "rb") as handle:
            now = handle.read()
        # Not equality: the failed-install screen carries a blinking cursor,
        # so consecutive frames differ by a few hundred bytes and an exact
        # comparison never counts them as unchanged. One install died after
        # 2m47s and was photographed 37 times over half an hour without this
        # detector noticing. A screen that differs only by a cursor is a
        # screen nobody is driving.
        unchanged = unchanged + 1 if last is not None and _same(now, last) else 0
        last = now
        if unchanged >= stuck_limit:
            print(
                f"install did not finish: the screen has not changed in "
                f"{stuck_limit * 45}s, so it is waiting on something this "
                f"driver did not answer",
                flush=True,
            )
            return
    print("install did not finish within the sampling window", flush=True)


if __name__ == "__main__":
    main()
