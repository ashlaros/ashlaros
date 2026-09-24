#!/usr/bin/env bash
#
# Chromium and Electron pick where to keep their encryption key from
# XDG_CURRENT_DESKTOP. "sway" is none of the desktops they know, so they
# fall back to the basic text store - a key that is the same on every
# machine - although gnome-keyring runs on every AshlarOS desktop. Code -
# OSS says so in a dialog at startup ("An OS keyring couldn't be
# identified"); the browsers do it silently.
#
# skel's *-flags.conf files now name the store. /etc/skel is copied once,
# at account creation, so existing copies get the line appended here. A
# file that already chooses a --password-store is the user's decision and
# is left alone, and a file the user deleted is not recreated.
set -uo pipefail

echo "Keep Chromium and Electron secrets in gnome-keyring"

dir="${XDG_CONFIG_HOME:-$HOME/.config}"
line='--password-store=gnome-libsecret'

for name in code brave chrome chrome-beta chrome-dev chromium \
    microsoft-edge-stable microsoft-edge-beta microsoft-edge-dev \
    electron electron12 electron18 electron20 youtube-music; do
    file="$dir/$name-flags.conf"
    [ -f "$file" ] || continue
    if grep -q -- '--password-store' "$file"; then
        echo "  $name-flags.conf already chooses a password store"
        continue
    fi
    # a file whose last line has no newline would otherwise get the flag
    # glued onto that line
    [ -n "$(tail -c1 "$file")" ] && printf '\n' >>"$file"
    printf '%s\n' "$line" >>"$file" || exit 1
    echo "  $name-flags.conf: added $line"
done
