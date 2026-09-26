#!/bin/sh
# Sway Binding Documentation Parser: the sway config's `## Category //
# Action // Keybinding ##` comments, as JSON.
#
# Replaces sbdp.py, vendored third-party Python we did not write. The parse
# is sbdp.awk; this supplies the glyphs and turns the \x1f-delimited records
# into the JSON shape the help overlay already consumed, so its consumer is
# unchanged.
#
# The glyphs live here rather than in the awk because awk source with nerd
# font codepoints in it is unreadable and unsearchable.

set -eu

here=$(dirname "$(readlink -f "$0")")
root=${1:-/etc/sway/config}

awk -v ROOT="$root" \
	-v MOD2="" \
	-v MOD3="󰘲" \
	-v SPACE="␣" \
	-v RETURN="󰌑" \
	-v VOL_UP="󰝝" \
	-v VOL_DOWN="󰝞" \
	-v VOL_MUTE="󰝟" \
	-v MIC_MUTE="󰍭" \
	-v BRIGHT_UP="󰃠" \
	-v BRIGHT_DOWN="󰃞" \
	-v POWER="󰐥" \
	-f "$here/sbdp.awk" </dev/null |
	jq -R -s 'split("\n") | map(select(length > 0)) | map(split("\u001f"))
	          | map({category: .[0], action: .[1], keybinding: .[2], mods: .[3], mode: .[4]})'
