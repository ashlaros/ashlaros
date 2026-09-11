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

import sys
import time

sys.path.insert(0, "/vm")
from qmp import Qmp

PASSWORD = "correcthorse"

# gum's selected-button background as the framebuffer renders it, measured
# off a real completion screen - not the 24-bit value the theme names. A
# run long enough to be a button rather than a stray pixel.
SELECTED = bytes([0xAA, 0x00, 0xAA]) * 8


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


def main():
    q = Qmp()

    # screen 1: locale & keyboard, EU default preselected
    q.shot("step-1-locale")
    q.key("ret")
    time.sleep(4)

    # screen 2: user. The username has a default, the passwords do not.
    q.shot("step-2-user")
    q.key("ret")
    time.sleep(4)
    q.type(PASSWORD)
    q.key("ret")
    time.sleep(3)
    q.type(PASSWORD)
    q.key("ret")
    time.sleep(4)
    q.shot("step-2-hostname")
    q.key("ret")
    time.sleep(3)
    q.key("ret")
    time.sleep(4)

    # screen 3: encryption & TPM, on by default
    q.shot("step-3-encryption")
    q.key("ret")
    time.sleep(4)

    # screen 4: layout, erase disk + btrfs by default
    q.shot("step-4-disk")
    q.key("ret")
    time.sleep(4)
    q.key("ret")
    time.sleep(4)

    q.shot("step-5-confirm")
    q.key("ret")

    # then the dashboard runs. Sample it until the prompt appears; under
    # TCG the install takes roughly 35 minutes.
    for i in range(120):
        time.sleep(45)
        path = q.shot(f"install-{i:02d}")
        if finished(path):
            time.sleep(5)
            q.key("ret")
            print("rebooting")
            return
    print("install did not finish within the sampling window")


if __name__ == "__main__":
    main()
