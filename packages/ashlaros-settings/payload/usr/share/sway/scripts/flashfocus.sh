#!/bin/sh
# Flash a window when it takes focus.
#
# Replaces the flashfocus package, which brought nine Python runtime
# dependencies and a vendored python-xpybutil that existed only for it.
# This does the same job with sway's own `opacity` command.
#
# Configuration is /etc/sway/flashfocus.conf, overridden per user by
# $XDG_CONFIG_HOME/sway/flashfocus.conf. It is a shell fragment rather than
# YAML, because reading YAML is what required Python.
#
# Not carried over from flashfocus: the per-window rules table, and
# flash-lone-windows' on_open_close/on_switch modes. Our shipped config used
# neither - `always`, and no rules - and they are the bulk of what is left of
# that program. flash-on-focus and flash-fullscreen are kept.
#
# Known behaviour, not a bug to fix later: a window whose opacity was set by
# a `for_window` rule is restored to default_opacity after its first flash.
# Nothing can read a window's current opacity - sway's IPC does not report
# alpha, and flashfocus itself raises NotImplementedError for the same
# read-back - so no implementation of this can preserve it.

set -eu

flash_opacity=0.8
default_opacity=1
time_ms=300
ntimepoints=20
simple=false
flash_on_focus=true
flash_fullscreen=false

for conf in /etc/sway/flashfocus.conf \
	"${XDG_CONFIG_HOME:-$HOME/.config}/sway/flashfocus.conf"; do
	# shellcheck source=/dev/null
	[ -r "$conf" ] && . "$conf"
done

[ "$flash_on_focus" = true ] || exit 0

flash_pid=

# Restore whatever we were mid-ramp on, so a killed animation never leaves a
# window transparent.
restore() {
	[ -n "${1:-}" ] && swaymsg "[con_id=$1] opacity $default_opacity" >/dev/null 2>&1
}

flash() {
	con_id=$1
	trap 'restore "$con_id"; exit 0' TERM

	if [ "$simple" = true ]; then
		swaymsg "[con_id=$con_id] opacity $flash_opacity" >/dev/null 2>&1 || exit 0
		sleep "$(awk -v t="$time_ms" 'BEGIN { print t / 1000 }')"
		restore "$con_id"
		exit 0
	fi

	# Schedule against a deadline rather than sleeping a fixed slice per
	# frame. A slow IPC round trip then eats the next frame's sleep instead
	# of stretching the whole animation, which is what makes flashfocus
	# overrun its configured time by up to 1.36x.
	start=$(date +%s.%N)
	i=0
	while [ "$i" -lt "$ntimepoints" ]; do
		opacity=$(awk -v f="$flash_opacity" -v d="$default_opacity" \
			-v i="$i" -v n="$ntimepoints" \
			'BEGIN { print f + (d - f) * (i / n) }')
		swaymsg "[con_id=$con_id] opacity $opacity" >/dev/null 2>&1 || exit 0

		i=$((i + 1))
		wait_for=$(awk -v s="$start" -v i="$i" -v t="$time_ms" -v n="$ntimepoints" \
			-v now="$(date +%s.%N)" \
			'BEGIN { d = s + i * (t / 1000 / n) - now; print (d > 0) ? d : 0 }')
		[ "$wait_for" = 0 ] || sleep "$wait_for"
	done
	restore "$con_id"
}

swaymsg -t subscribe -m '["window"]' | while read -r event; do
	case $(printf '%s' "$event" | jq -r '.change') in
	focus) ;;
	*) continue ;;
	esac

	con_id=$(printf '%s' "$event" | jq -r '.container.id')
	[ -n "$con_id" ] && [ "$con_id" != null ] || continue

	if [ "$flash_fullscreen" != true ]; then
		case $(printf '%s' "$event" | jq -r '.container.fullscreen_mode') in
		0 | null) ;;
		*) continue ;;
		esac
	fi

	# Kill *and wait for* the previous flash. Killing alone lets its restore
	# race the next flash's first frame, and the two interleave; waiting
	# means the abandoned window is back at default_opacity before anything
	# else writes to it.
	if [ -n "$flash_pid" ] && kill -0 "$flash_pid" 2>/dev/null; then
		kill -TERM "$flash_pid" 2>/dev/null || true
		wait "$flash_pid" 2>/dev/null || true
	fi

	flash "$con_id" &
	flash_pid=$!
done
