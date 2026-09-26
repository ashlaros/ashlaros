# fix for screen readers
if grep -Fqa 'accessibility=' /proc/cmdline &> /dev/null; then
    setopt SINGLE_LINE_ZLE
fi

# The live session is a sway desktop on tty1, which runs the installer in a
# terminal window so other tools (like a browser) are available alongside it.
#
# As the live user, not root (#101). A getty login gets a user session from
# logind, so XDG_RUNTIME_DIR is already /run/user/1000 and owned by us; the
# fallback is for a login that somehow did not get one, which is otherwise a
# sway that cannot open its socket.
[[ $(tty) == /dev/tty1 ]] || return 0

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
[[ -d $XDG_RUNTIME_DIR ]] || {
    mkdir -p "$XDG_RUNTIME_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"
}

exec sway -c /etc/sway/config >"$HOME/.live-session.log" 2>&1
