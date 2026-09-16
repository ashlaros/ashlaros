#!/usr/bin/env bash
#
# The keybinding help overlay moved from nwg-wrapper to eww (#74). /etc/skel
# is copied once at account creation, so a $HOME made before this has
# ~/.config/nwg-wrapper/ and no eww config at all - the autostart guard
# tests for ~/.config/eww/eww.yuck, so the overlay would simply never
# appear again.
set -uo pipefail

echo "Move the help overlay from nwg-wrapper to eww (#74)"

eww_dir="$HOME/.config/eww"
nwg_dir="$HOME/.config/nwg-wrapper"

# Seeded from skel, and only where absent: a user who wrote their own eww
# config keeps it.
seed_once() {
    local src="/etc/skel/.config/eww/$1" dst="$eww_dir/$1"
    [ -f "$src" ] || return 0
    if [ -e "$dst" ]; then
        echo "  $1 already exists, leaving it alone"
        return 0
    fi
    mkdir -p "$eww_dir"
    cp -- "$src" "$dst"
    echo "  seeded $1 from skel"
}

seed_once eww.yuck
seed_once eww.css

# The old config is left in place rather than deleted. It is three small
# files in the user's own directory, nothing reads them once nwg-wrapper is
# gone, and removing a config a user may have edited is not this script's
# call to make.
if [ -d "$nwg_dir" ]; then
    echo "  $nwg_dir is no longer read; remove it when you like"
fi
