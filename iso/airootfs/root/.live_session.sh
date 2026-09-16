#!/usr/bin/env bash
#
# Live session entry point on tty2: start sway so someone can look
# something up mid-install without disturbing the installer.
#
# The ISO has carried sway, foot and firefox since the beginning with
# nothing to start them (#83). tty1 belongs to the installer dashboard for
# the whole install, so the session lives on its own VT and the installer
# never loses the screen it owns.
set -uo pipefail

[[ $(tty) == /dev/tty2 ]] || exit 0

# sway needs a seat. A real VT login gives logind one, which is why this
# runs from the autologin rather than from a unit with no session attached.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
[[ -d $XDG_RUNTIME_DIR ]] || {
    mkdir -p "$XDG_RUNTIME_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"
}

# The installer is still running on tty1 and owns the log. Sway's own
# output would interleave with nothing useful, so it goes to its own file.
exec sway -c /etc/sway/config >/var/log/live-session.log 2>&1
