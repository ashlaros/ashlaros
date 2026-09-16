#!/bin/sh
# Show or hide the keybinding help overlay.
#
# Was one nwg-wrapper process per output, spawned by a `swaymsg -t
# get_outputs` loop and toggled by sending SIGPWR to a pkill argv match.
# eww's daemon owns the window instead, so a toggle is one command and a
# `swaymsg reload` does not respawn anything.
#
# $HOME/.local/help_disabled stays as the off switch. It is what
# screenshots/session.sh touches to keep the overlay out of published
# screenshots, and it is what remembers a dismissal across a logout.

set -eu

LOCKFILE="$HOME/.local/help_disabled"

command -v eww >/dev/null || exit 0

case "${1:-}" in
--toggle)
	mkdir -p "$(dirname "$LOCKFILE")"
	if [ -f "$LOCKFILE" ]; then
		rm -f "$LOCKFILE"
	else
		touch "$LOCKFILE"
	fi
	eww open --toggle help >/dev/null 2>&1 || true
	;;
*)
	# Session start. eww starts its own daemon on `open`, so there is no
	# separate daemon line, and opening a window that is already open is a
	# no-op rather than a second copy.
	[ -f "$LOCKFILE" ] && exit 0
	eww open help >/dev/null 2>&1 || true
	;;
esac
