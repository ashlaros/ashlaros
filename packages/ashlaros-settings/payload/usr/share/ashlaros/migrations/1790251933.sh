#!/usr/bin/env bash
#
# The prompt's colours are derived from $background-color, $text-color and
# $accent-color now, so the $prompt-* block every theme.conf briefly
# carried is gone from the shipped themes - and 1790244343, which copied it
# into ~/.config/sway/definitions.d, with it. A copy that got the block is
# no longer byte-identical to any shipped theme, so the settings TUI's
# Theme entry would call it edited. This takes the block back out.
#
# Only the block, exactly as it was shipped: a blank line, the two comment
# lines, seven `set $prompt-` lines. Anything else in the file is kept.
set -uo pipefail

echo "Drop the unused prompt colours from the active sway theme"

dir="$HOME/.config/sway/definitions.d"

strip_prompt() {
    awk '{ l[++n] = $0 }
        END {
            for (i = 1; i <= n; i++) {
                if (l[i] == "" && l[i + 1] ~ /^# the prompt.s segments, named for starship/) { i += 9; continue }
                print l[i]
            }
        }' "$1"
}

for copy in "$dir/theme.conf" "$dir/theme.light.conf_"; do
    [ -f "$copy" ] || continue
    if ! grep -q '^# the prompt.s segments, named for starship' "$copy"; then
        echo "  $(basename "$copy") has no prompt block"
        continue
    fi
    # the original stays as theme.conf~, the backup name the theme
    # switcher's cp --backup uses
    cp -- "$copy" "$copy~" || exit 1
    strip_prompt "$copy~" >"$copy" || exit 1
    echo "  $(basename "$copy"): removed the prompt block"
done
