#!/bin/sh
# Show or hide the keybinding help overlay.
#
# Two eww windows (#89). `help` is the whole sheet: shown on a first login
# and toggled by Super+?, as it always was. `help-keys` is open for the
# whole session, once per output, and draws nothing until keys are held,
# then the bindings that fit them - see eww.yuck and help-keys.sh.
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
#
# The sheet opens on the focused output, which with sway's default
# focus_follows_mouse is the one under the cursor. eww cannot follow the
# cursor itself: :monitor takes an index, a name or <primary> and nothing
# else, and leaving it out fails outright - sway gives GTK no primary. So
# `--screen` overrides the yuck's :monitor 0 on each open. An index, not a
# name: under wayland eww 0.5.0 sees every monitor's model as "Unknown".
# GDK numbers the wl_outputs in the order sway lists its active outputs,
# measured on two - eDP-1 first there, and `--screen 0` landed on it.
#
# The held keys cannot be reopened that way: they show the moment a
# modifier goes down, and `eww open` is 55 ms. So there is one help-keys
# per output, each given its index as `screen`, and help-keys.sh says which
# index has focus - only that one draws.
#
# --outputs is help-keys.sh's, after a hotplug.

set -eu

LOCKFILE="$HOME/.local/help_disabled"

command -v eww >/dev/null || exit 0

focused_screen() {
	screen=$(swaymsg -t get_outputs --raw 2>/dev/null |
		jq '[.[] | select(.active)] | map(.focused) | index(true) // 0' 2>/dev/null) || screen=
	printf '%s' "${screen:-0}"
}

# A help-keys for every active output, and none past them. eww closes and
# recreates a window that is already open - which restarts the watcher
# once no other instance reads it, and would lose a held modifier on every
# reload - so an open one is left alone. Unless $1 is reopen: a hotplug
# renumbers GDK's monitors, and each instance has to move to its index.
#
# Instances are opened before any is closed, so the watcher always has a
# reader. That includes the one window named plain help-keys, from before
# there was one per output.
keys_windows() {
	count=$(swaymsg -t get_outputs --raw 2>/dev/null |
		jq '[.[] | select(.active)] | length' 2>/dev/null) || count=
	count=${count:-1}
	open=$(eww active-windows 2>/dev/null) || open=
	i=0
	while [ "$i" -lt "$count" ]; do
		if [ "${1:-}" = reopen ] || ! printf '%s\n' "$open" | grep -qx "help-keys-$i: help-keys"; then
			eww open help-keys --id "help-keys-$i" --arg screen="$i" >/dev/null 2>&1 || true
		fi
		i=$((i + 1))
	done
	printf '%s\n' "$open" | sed -n 's/^\(help-keys[-0-9]*\): help-keys$/\1/p' |
		while read -r id; do
			i=${id#help-keys-}
			case "$i" in
			'' | *[!0-9]*) ;;
			*) [ "$i" -lt "$count" ] && continue ;;
			esac
			eww close "$id" >/dev/null 2>&1 || true
		done
}

case "${1:-}" in
--toggle)
	mkdir -p "$(dirname "$LOCKFILE")"
	if [ -f "$LOCKFILE" ]; then
		rm -f "$LOCKFILE"
	else
		touch "$LOCKFILE"
	fi
	eww open --toggle --screen "$(focused_screen)" help >/dev/null 2>&1 || true
	;;
--outputs)
	keys_windows reopen
	;;
*)
	# Session start, and every reload. eww starts its own daemon on
	# `open`, so there is no separate daemon line. The sheet, like the
	# held keys, is opened only when it is not already.
	keys_windows
	[ -f "$LOCKFILE" ] && exit 0
	case "$(eww active-windows 2>/dev/null)" in
	*"help: help"*) ;;
	*) eww open --screen "$(focused_screen)" help >/dev/null 2>&1 || true ;;
	esac
	;;
esac
