"""Type at the VM's console and screenshot its framebuffer, over QMP.

There is no other channel. The loader entry carries no `console=ttyS0`, so
the kernel, the gum TUI and the desktop all draw only on the virtual
console; reading a file on the guest means typing `cat` at the framebuffer
and taking a picture of the result.

Keyboard layouts are the sharp edge. QMP sends *qcodes* - physical key
positions - so what a keystroke produces depends on the keymap the guest
has loaded. The live ISO is US-positioned; an installed system runs
whatever keymap the installer configured, `de` by default. Hence two
tables: `type()` for the installer, `type_de()` for the installed desktop.
Getting this wrong is not subtle - `swaymsg -t get_inputs` arrives as
`swazmsg ßt get?inputs`.
"""

import json
import os
import socket
import sys
import time

SOCKET = "/vm/qmp.sock"

# What a US-positioned console makes of each qcode.
KEYS = {
    " ": "spc",
    "-": "minus",
    "/": "slash",
    ".": "dot",
    ",": "comma",
    "_": "shift-minus",
    "=": "equal",
    ":": "shift-semicolon",
    ";": "semicolon",
    "'": "apostrophe",
    "*": "shift-8",
    "|": "shift-backslash",
    ">": "shift-dot",
    "<": "shift-comma",
    "(": "shift-9",
    ")": "shift-0",
    "$": "shift-4",
    "!": "shift-1",
    "?": "shift-slash",
    "+": "shift-equal",
    "~": "shift-grave_accent",
    "\\": "backslash",
    "[": "bracket_left",
    "]": "bracket_right",
    "{": "shift-bracket_left",
    "}": "shift-bracket_right",
    '"': "shift-apostrophe",
    "#": "shift-3",
    "&": "shift-7",
    "%": "shift-5",
    "@": "shift-2",
}

# The qcodes that PRODUCE the wanted character on a de keymap. Only the
# keys that move need an entry; the rest fall through to KEYS.
DE_KEYS = dict(
    KEYS,
    **{
        "-": "slash",
        "/": "shift-7",
        "_": "shift-slash",
        "=": "shift-0",
        "y": "z",
        "z": "y",
        # de puts these where us has the semicolon and quote keys
        ";": "shift-comma",
        ":": "shift-dot",
        "'": "shift-backslash",
        # AltGr characters. Inherited from KEYS these land on whatever de
        # puts at the us position - a piped command arrives as an unclosed
        # quote and the shell sits at a continuation prompt, which reads
        # like a hung guest rather than a typo.
        "|": "alt_r-less",
        "\\": "alt_r-minus",
        "@": "alt_r-q",
        "~": "alt_r-bracket_right",
        "[": "alt_r-8",
        "]": "alt_r-9",
        "{": "alt_r-7",
        "}": "alt_r-0",
    },
)


class Qmp:
    """A QMP client: keys in, screenshots out."""

    def __init__(self, path=SOCKET):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.file = self.sock.makefile("rw")
        self.file.readline()  # the greeting
        self.cmd("qmp_capabilities")

    def cmd(self, execute, **arguments):
        payload = {"execute": execute}
        if arguments:
            payload["arguments"] = arguments
        self.file.write(json.dumps(payload) + "\n")
        self.file.flush()
        while True:
            line = self.file.readline()
            if not line:
                return None
            reply = json.loads(line)
            # events arrive unsolicited and are not the answer to anything
            if "event" in reply:
                continue
            return reply

    def key(self, name):
        """Send one key, `ctrl-alt-delete` style for combinations."""
        keys = [{"type": "qcode", "data": part} for part in name.split("-")]
        self.cmd("send-key", keys=keys)

    def type(self, text, layout=KEYS):
        for ch in text:
            if ch.isupper():
                self.key("shift-" + ch.lower())
            else:
                self.key(layout.get(ch, ch))
            # without a gap the guest's input layer drops characters
            time.sleep(0.05)

    def type_de(self, text):
        """Type on a guest running the de keymap - i.e. after install."""
        self.type(text, DE_KEYS)

    def shot(self, name):
        """Screenshot the framebuffer to /vm/out/<name>.ppm."""
        path = f"/vm/out/{name}.ppm"
        self.cmd("screendump", filename=path)
        # screendump returns before the file is written
        for _ in range(40):
            if os.path.exists(path) and os.path.getsize(path) > 0:
                time.sleep(0.5)
                return path
            time.sleep(0.5)
        return path


def main():
    """Run a command on the guest and screenshot the result.

    usage: qmp.py '<command>' <screenshot-name> [seconds to wait]

    An empty command just screenshots what is on screen.
    """
    command, name = sys.argv[1], sys.argv[2]
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 6

    q = Qmp()
    if command:
        q.type(command)
        q.key("ret")
    time.sleep(delay)
    q.shot(name)
    print("captured", name)


if __name__ == "__main__":
    main()
