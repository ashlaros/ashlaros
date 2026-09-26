#!/bin/sh
# Show or hide the keybinding help overlay.
#
# Two eww windows (#89). `help` is the whole sheet: shown on a first login
# and toggled by Super+?, as it always was. `help-keys` is open for the
# whole session and draws nothing until keys are held, then the bindings
# that fit them - see eww.yuck and help-keys.sh.
#
# Was one nwg-wrapper process per output, spawned by a `swaymsg -t
# get_outputs` loop and toggled by sending SIGPWR to a pkill argv match.
# eww's daemon owns the windows instead, so a toggle is one command and a
# `swaymsg reload` does not respawn anything.
#
# $HOME/.local/help_disabled stays as the off switch for the whole sheet.
# It is what screenshots/session.sh touches to keep the overlay out of
# published screenshots, and it is what remembers a dismissal across a
# logout. The held-keys window ignores it: it is empty until asked for.

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
	# Session start, and every reload. eww starts its own daemon on
	# `open`, so there is no separate daemon line. It also closes and
	# recreates a window that is already open - which for help-keys
	# restarts its watcher, and would lose a held modifier on every
	# reload - so each is opened only when it is not.
	open=$(eww active-windows 2>/dev/null) || open=
	case "$open" in
	*"help-keys: help-keys"*) ;;
	*) eww open help-keys >/dev/null 2>&1 || true ;;
	esac
	[ -f "$LOCKFILE" ] && exit 0
	case "$open" in
	*"help: help"*) ;;
	*) eww open help >/dev/null 2>&1 || true ;;
	esac
	;;
esac
