#!/usr/bin/env sh
set -u

export CROWN=$1
export ROOT=$2
export BACKGROUND=$3

# The wallpaper is written here and applied by $apply_background, from a
# different exec_always block, and sway runs the two concurrently. envsubst
# with a plain redirect truncates the file before it writes, so an apply
# that won the race gave swaybg an empty SVG. Measured frame by frame in
# the tour recording: the theme switch left the desktop black until a
# window covered it, 2.8 s later; with this, 0.3 s while swaybg restarts.
#
# So the file is replaced whole, by rename, which swaybg can only ever see
# as the old wallpaper or the new one; and applied again once the new one
# is in place, because an apply that ran first loaded the old colours.
target="$HOME/.config/sway/generated_background.svg"
tmp="$target.$$"
envsubst < /usr/share/sway/templates/ashlaros-scalable.svg > "$tmp" &&
    mv -f "$tmp" "$target" || { rm -f "$tmp"; exit 1; }

[ -n "${SWAYSOCK:-}" ] && swaymsg "output * bg $target fill" >/dev/null 2>&1
exit 0
