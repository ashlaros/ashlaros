#!/bin/sh
# The keybinding help overlay's live half (#89): what is held, and which
# bindings fit it, as one JSON line per change for eww's deflisten -
#
#   {"show": true, "entries": [{"action": ..., "keybinding": ...}, ...]}
#
# sway has no IPC event for a key being pressed - `binding` fires only for a
# binding that already exists. So the modifiers are read off four bars that
# never draw: etc/sway/config.d/95-help-keys.conf declares one per modifier,
# `modifier Mod4` and so on with swaybar_command /bin/true, and sway sends
# bar_state_update each time that modifier goes down or up. A `bindsym
# Super_L` would say the same, and it eats chords: measured on sway 1.9 it
# swallowed Super+d outright in one ordering, and its --release half never
# fired once any other binding ran in between, which would leave the
# overlay stuck open.
#
# The held modifiers are a four-letter mask - s Super, h sHift, c Ctrl, a
# Alt, "-" where not held - the same one sbdp.awk writes for each binding,
# so the filter compares two strings. It runs here, in jq, and not in eww:
# the filter needs the current mode's name, and every one of ours is pango
# markup full of quotes that would have to be spliced into jq source.
#
# Hidden once a binding fires, which is when the sheet has done its job,
# and until every modifier is up - so holding Super and pressing d twice
# does not flash it back between the two.
#
# Measured on sway 1.12: the bar event arrives 1.8 ms after the key.
set -u

sheet=$(/usr/share/sway/scripts/sbdp.sh "${1:-$HOME/.config/sway/config}")

mods=----
mode=default
fired=false

# The candidates: in the current mode, and needing every modifier held.
# Needing it, not only it: with Super held, Super+Shift+q is still one key
# away. So a binding stays when, at each position the held mask has a
# letter, its own mask has one too - "s---" keeps "sh--", "sh--" drops
# "s---". Inside a mode other than default the mode's keys are the whole
# answer, modifiers or not. Fewest modifiers first, so the next key to
# press is at the top.
emit() {
	printf '%s' "$sheet" | jq -c --arg mods "$mods" --arg mode "$mode" --argjson fired "$fired" '
		map(select(.mode == $mode)
		    | select($mode != "default" or
		             (.mods as $need | [range(4)]
		              | all(. as $i | $mods[$i:$i+1] == "-" or $need[$i:$i+1] != "-"))))
		| sort_by((.mods | gsub("-"; "") | length), .category)
		# Shift alone is typing, not a lookup: capitals and every symbol
		# on the number row. Showing the sheet for it would cover the
		# screen on each one.
		| {show: ((($mods != "----" and $mods != "-h--") or ($mode != "default"))
		          and ($fired | not) and length > 0),
		   entries: map({action, keybinding})}'
}

emit
swaymsg -t subscribe -m '["bar_state_update","binding","mode"]' |
	jq --unbuffered -r '
		if .id then "bar\t\(.id)\t\(.visible_by_modifier)"
		elif .binding then "binding"
		elif .change then "mode\t\(.change)"
		else empty end' |
	while IFS="$(printf '\t')" read -r kind a b; do
		case "$kind" in
		bar)
			case "$a" in
			help-keys-super) i=1 ;;
			help-keys-shift) i=2 ;;
			help-keys-ctrl) i=3 ;;
			help-keys-alt) i=4 ;;
			*) continue ;;
			esac
			letter=$(printf 'shca' | cut -c"$i")
			[ "$b" = true ] || letter=-
			mods=$(printf '%s' "$mods" | awk -v i="$i" -v l="$letter" \
				'{ print substr($0, 1, i - 1) l substr($0, i + 1) }')
			# every modifier up: the next press starts a fresh lookup
			[ "$mods" = ---- ] && fired=false
			;;
		binding)
			# Entering a mode is a binding too, and the one moment the
			# sheet should stay up: the next key is chosen from the mode's
			# own list. The mode event arrives first and says so.
			[ "$mode" = default ] && fired=true
			;;
		mode)
			mode=$a
			fired=false
			;;
		esac
		emit
	done
