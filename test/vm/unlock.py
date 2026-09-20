"""Type the LUKS passphrase at the installed system's boot prompt.

The installer asks how the disk should unlock and defaults to a
passphrase, so the machine that comes back after the install waits for one
before it can reach a desktop. Nothing typed it, and the desktop wait saw
a black screen for its whole 90-minute deadline.

The prompt is drawn by the initramfs on the framebuffer, not the serial
console, so this waits for the screen to stop being the loader menu rather
than matching text: any non-black, non-menu screen at this point in the
boot is the passphrase prompt, and typing into a screen that is already
past it costs nothing - the characters land on a tty nobody reads.

Keyboard layout is the *installer's* default here, not the installed
system's: the initramfs asks before vconsole is configured.
"""

import sys
import time

sys.path.insert(0, "/vm")
from qmp import Qmp

PASSWORD = "correcthorse"


def darkness(raw):
    """Share of the framebuffer that is effectively black."""
    body = raw[raw.index(b"255\n") + 4 :]
    pixels = [body[i : i + 3] for i in range(0, len(body) - 2, 3)]
    if not pixels:
        return 1.0
    return sum(1 for p in pixels if max(p) < 24) / len(pixels)


def main():
    q = Qmp()

    # The loader menu counts down, then the kernel takes the console and
    # the screen goes black until the initramfs draws its prompt. Wait for
    # something to be on it again.
    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(5)
        with open(q.shot("unlock-probe"), "rb") as handle:
            dark = darkness(handle.read())
        # a passphrase prompt is a line or two of text on black; a fully
        # black screen is the gap between the loader and the initramfs
        if dark < 0.999:
            q.shot("unlock-prompt")
            q.type(PASSWORD)
            q.key("ret")
            print("typed the passphrase", flush=True)
            return 0
    print("no passphrase prompt appeared", flush=True)

    # Type it anyway. A TPM-unlocked machine shows no prompt and the
    # characters land on a tty nobody reads, which costs nothing. But an
    # invisible prompt takes them and the boot continues - and that is the
    # difference between "the prompt is drawn where nothing shows it" and
    # "the initramfs never asked", which a black frame alone cannot tell
    # apart (#86).
    #
    # That was a plymouth splash answering `plymouth --ping` and rendering
    # nothing, so the encrypt hook skipped its own console fallback. The
    # splash is gone (#106), but the distinction is still worth keeping:
    # any boot that waits on a secret without showing it looks identical
    # to one that hung.
    q.type(PASSWORD)
    q.key("ret")
    print("typed it blind, in case the prompt is drawn but not visible", flush=True)

    # Not a failure either way: the desktop wait after this decides the
    # test, and it now reports a frozen screen rather than waiting out the
    # clock.
    return 0


if __name__ == "__main__":
    sys.exit(main())
