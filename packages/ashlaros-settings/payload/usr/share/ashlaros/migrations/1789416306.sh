#!/usr/bin/env bash
#
# b2eb672 added the LD_PRELOAD that makes gtk-nocsd do anything, to skel's
# .profile. /etc/skel is copied once at user creation, so a $HOME made
# before that commit has GTK_CSD=0 and no library to read it - which is
# exactly the inert state that commit existed to fix, now preserved for
# everyone who already had an account (#35).
#
# etc/sway/autostart carries the other half and is a system file, so it
# updates with the package and needs nothing here. Only .profile is
# per-user.
set -uo pipefail

echo "Preload gtk-nocsd, so GTK_CSD=0 means something (#35)"

profile="$HOME/.profile"

if [ ! -f "$profile" ]; then
    echo "  no ~/.profile; nothing to update"
    exit 0
fi

# Already there - either from a newer skel or from a previous run. Adding
# a second export would leave the library named twice in LD_PRELOAD, which
# works but is the kind of thing that confuses the next person to read it.
if grep -q 'libgtk-nocsd\.so' "$profile"; then
    echo "  already preloaded"
    exit 0
fi

# Only where GTK_CSD is: a $HOME whose .profile no longer has that line
# has been edited deliberately, and appending a preload to someone's own
# file is not this script's business.
if ! grep -q '^export GTK_CSD=' "$profile"; then
    echo "  no GTK_CSD line to pair with; leaving ~/.profile alone"
    exit 0
fi

# Appended directly after GTK_CSD, because the two belong together: the
# variable configures the library, and neither does anything without the
# other. The ${LD_PRELOAD:+:...} keeps whatever the user already preloads.
tmp=$(mktemp) || exit 1
awk '
    { print }
    /^export GTK_CSD=/ && !done {
        print "# gtk-nocsd is what makes the line above mean anything: GTK_CSD is read"
        print "# by the preloaded library, not by GTK."
        print "export LD_PRELOAD=\"/usr/lib/libgtk-nocsd.so${LD_PRELOAD:+:$LD_PRELOAD}\""
        done = 1
    }
' "$profile" > "$tmp" || { rm -f "$tmp"; exit 1; }

# Written in place rather than moved over: .profile may be a symlink into
# a dotfiles repository, and replacing it would break that link.
cat "$tmp" > "$profile" || { rm -f "$tmp"; exit 1; }
rm -f "$tmp"
echo "  added the LD_PRELOAD beside GTK_CSD in ~/.profile"

# Said rather than silently true. Migrations run from sway's autostart
# (config.d/99-autostart-applications.conf), which is long after greetd
# has already run `sh -lc sway` and read .profile - and after
# $import_environment has handed that environment to the systemd user
# manager. So nothing in this session sees the new variable.
#
# The #18 migration could regenerate the file it changed and make its
# effect immediate; a login shell cannot be re-sourced into a session that
# is already running, so this one reports instead of pretending.
echo "  GTK apps keep their headerbars until the next login."
