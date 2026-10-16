#!/usr/bin/env bash
#
# Camera reactions took one camera, ASHLAROS_REACTIONS_CAMERA; they now
# take a list, ASHLAROS_REACTIONS_CAMERAS, best first. The one camera
# someone chose becomes the head of that list, so the choice is kept -
# and a camera plugged in later, which the list does not name yet, still
# gets used when the chosen one is absent.
set -uo pipefail

conf="${XDG_CONFIG_HOME:-$HOME/.config}/ashlaros/reactions.conf"
[ -f "$conf" ] || exit 0
grep -q '^ASHLAROS_REACTIONS_CAMERA=' "$conf" || exit 0

echo "Camera reactions: one chosen camera becomes the top of a list"

camera=$(sed -n 's/^ASHLAROS_REACTIONS_CAMERA=//p' "$conf" | head -1)
tmp=$(mktemp "$conf.XXXXXX") || exit 1
{
    grep -v '^ASHLAROS_REACTIONS_CAMERA=' "$conf"
    [ -n "$camera" ] && echo "ASHLAROS_REACTIONS_CAMERAS=\"$camera\""
} > "$tmp"
# in place rather than moved over: it may be a symlink into a dotfiles
# repository, and replacing it would break the link
cat -- "$tmp" > "$conf"
rm -f -- "$tmp"
echo "  kept $camera as the first camera"
