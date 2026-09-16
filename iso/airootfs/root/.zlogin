# fix for screen readers
if grep -Fqa 'accessibility=' /proc/cmdline &> /dev/null; then
    setopt SINGLE_LINE_ZLE
fi

~/.automated_script.sh

# The live session, on its own VT. .automated_script.sh guards on tty1 and
# exits anywhere else, so this is only reached on tty2 - the installer on
# tty1 is untouched and keeps the screen it owns.
~/.live_session.sh
