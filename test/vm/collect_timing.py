#!/usr/bin/env python3
"""Copy the orchestrator's per-phase timings off the live ISO.

The weights in `installer/orchestrator/weights.py` have to come from a
real install or they are a table that looks measured and is not. This is
what measures one.

`<target>/var/log/ashlaros-install-timing.json` is the obvious source and
the wrong one: that path is inside the installed system's LUKS volume, so
reading it means unlocking and booting the guest first. The same document
is written to `/run/ashlaros-install/state.json` on the **live ISO**
(`phases.py` writes both), which is an unencrypted tmpfs this driver can
read the moment the install finishes - and before the reboot throws it
away.

Typed on tty1 after the dashboard has finished, where the shell that
launched it is waiting at the "Reboot?" prompt. The serial console is the
transport because it is the one channel that survives having no network
and no shared filesystem, and `verbose_boot.py` already proves the guest
writes to it.

Base64, in one line, for two reasons: the JSON carries `{`, `}` and `"`,
which are the characters this harness's keymap tables get wrong most
often (see qmp.py's DE_KEYS notes), and a payload that arrives corrupted
would still parse as *something* and produce a plausible wrong table.
Base64 either decodes or does not.
"""

import base64
import json
import re
import sys
import time
from pathlib import Path

from qmp import Qmp

OUT = Path("/vm/out")
SERIAL = OUT / "serial.log"
# the marker is echoed either side of the payload, so the reader takes the
# base64 and not whatever else the console said while it was typing
BEGIN = "ASHLAROS_TIMING_BEGIN"
END = "ASHLAROS_TIMING_END"


def decline_reboot(vm: Qmp) -> None:
    """Answer the dashboard's "Reboot?" with "Stay here".

    Until this is answered there is no shell on tty1 to type into: the
    dashboard is still in the foreground holding a gum confirm. "Reboot
    now" is the affirmative and the default, so Right moves to the
    negative - and taking the reboot here would wipe the tmpfs this came
    for.
    """
    vm.key("right")
    vm.key("ret")
    # the dashboard exits and .automated_script.sh falls back to its shell
    time.sleep(5)


def request(vm: Qmp) -> None:
    """Ask tty1 to print the state file to the serial console.

    `base64 -w0` rather than `cat`: see the module docstring. The redirect
    is the one character here the keymap tables are most likely to get
    wrong, so the command uses as few of them as it can.
    """
    vm.type(
        f"echo {BEGIN} > /dev/ttyS0; "
        f"base64 -w0 /run/ashlaros-install/state.json > /dev/ttyS0; "
        f"echo {END} > /dev/ttyS0"
    )
    vm.key("ret")


def harvest(deadline: float) -> dict | None:
    """The decoded state document, once the whole payload has arrived.

    The LAST begin-marker, not the first: tty1 echoes the command as it is
    typed, so the word ASHLAROS_TIMING_BEGIN appears on the console once in
    the echoed command line and again when the command runs. Anchoring on
    the first match swallows the rest of the echoed command into the
    payload, and since the filter below strips everything outside the
    base64 alphabet the result still decodes - to bytes that are not JSON.
    """
    while time.time() < deadline:
        time.sleep(3)
        if not SERIAL.exists():
            continue
        text = SERIAL.read_text(errors="replace")
        if END not in text:
            continue
        head, _, _tail = text.rpartition(END)
        _, marker, body = head.rpartition(BEGIN)
        if not marker:
            continue
        # the console wraps and echoes, so everything that is not base64
        # alphabet is noise the terminal added
        payload = re.sub(r"[^A-Za-z0-9+/=]", "", body)
        try:
            return json.loads(base64.b64decode(payload))
        except (ValueError, UnicodeDecodeError):
            # a partial or mis-anchored payload is not the document; the
            # console may still be mid-write, so wait for the rest
            continue
    return None


def report(state: dict) -> None:
    phases = [p for p in state.get("phases", []) if p.get("status") == "ok"]
    total = sum(p["elapsed"] for p in phases)
    print(f"== {len(phases)} phases, {total:.1f}s total", flush=True)
    for phase in phases:
        share = phase["elapsed"] / total * 100 if total else 0
        print(f"   {phase['elapsed']:8.1f}s  {share:5.1f}%  {phase['name']}", flush=True)


def main() -> int:
    vm = Qmp()
    decline_reboot(vm)
    request(vm)
    state = harvest(time.time() + 120)
    if state is None:
        print("no timing payload arrived on the serial console", flush=True)
        return 1

    (OUT / "install-timing.json").write_text(json.dumps(state, indent=2))
    report(state)
    print(f"== wrote {OUT / 'install-timing.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
