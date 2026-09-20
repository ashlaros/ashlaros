#!/usr/bin/env python3
"""Boot the installed disk on its verbose loader entry.

The default entry has no serial console, so a boot that goes wrong prints
nothing the host can read: the serial log ends at the loader countdown.
add_verbose_entry writes a second entry beside it with console=ttyS0
added, for exactly this.

That is what this selects. The menu lists the ordinary entry first and the
verbose copy second - filename order, since neither carries a sort-key -
so one Down and Enter picks it, and everything the initramfs says lands in
the host's serial log.

Written for #86, when a splash was hiding the passphrase prompt. The
splash is gone (#106), but a boot that stalls before the desktop still
says nothing on the framebuffer worth reading, and this is where the
initramfs gets to explain itself.
"""

import sys
import time

from qmp import Qmp

PASSWORD = "correcthorse"


def main() -> int:
    vm = Qmp()

    # The loader counts down before it boots the default. Down moves to the
    # verbose entry and stops the countdown; Enter takes it.
    time.sleep(3)
    vm.key("down")
    time.sleep(1)
    vm.shot("verbose-menu")
    vm.key("ret")
    print("selected the verbose entry", flush=True)

    # Then the passphrase, typed blind after a pause long enough for the
    # initramfs to reach its prompt. Blind because the whole question here
    # is that the prompt cannot be seen; the serial log is what answers it.
    time.sleep(45)
    vm.shot("verbose-prompt")
    vm.type(PASSWORD)
    vm.key("ret")
    print("typed the passphrase", flush=True)

    time.sleep(30)
    vm.shot("verbose-after")
    return 0


if __name__ == "__main__":
    sys.exit(main())
