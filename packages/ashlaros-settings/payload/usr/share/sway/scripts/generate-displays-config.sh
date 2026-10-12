#!/usr/bin/env bash
# Writes ~/.config/sway/config.d/99-displays.conf with current output scales
# from way-displays, so swaymsg reload uses correct scales without flickering.
# Called as way-displays CALLBACK_CMD, so scales are already applied by the time this runs.
set -u

OUTFILE="$HOME/.config/sway/config.d/99-displays.conf"

mkdir -p "$(dirname "$OUTFILE")"

# a disabled output, e.g. eDP-1 with the lid closed, reports scale null, which
# sway rejects as "Invalid scale" on the next reload
swaymsg -t get_outputs | jq -r '.[] | select(.scale != null) | "output \(.name) scale \(.scale)"' > "$OUTFILE"
