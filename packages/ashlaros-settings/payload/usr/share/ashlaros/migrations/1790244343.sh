#!/usr/bin/env bash
#
# Every theme.conf gained $prompt-* variables, which the starship generator
# now takes its colours from. The theme switcher copies the chosen
# theme.conf to ~/.config/sway/definitions.d/theme.conf, and a copy made
# before that lacks them - sway then takes them from $theme's system file,
# so the prompt is coloured by whichever theme ~/.config/sway/config names
# rather than the one the user picked.
#
# A copy is replaced only when it is a shipped theme.conf byte for byte
# once the prompt block is taken out: that is a copy nobody edited, and the
# new file is the same theme plus the block. An edited copy is left alone.
# The light half (theme.light.conf_) is handled the same way.
set -uo pipefail

echo "Give the active sway theme its prompt colours"

dir="$HOME/.config/sway/definitions.d"
themes=/usr/share/sway/themes

# The block as it was added after $accent-color: a blank line, two comment
# lines, seven $prompt- lines.
strip_prompt() {
    awk '{ l[++n] = $0 }
        END {
            for (i = 1; i <= n; i++) {
                if (l[i] == "" && l[i + 1] ~ /^# the prompt.s segments, named for starship/) { i += 9; continue }
                print l[i]
            }
        }' "$1"
}

refresh() {
    local copy=$1 shipped
    [ -f "$copy" ] || return 0
    if grep -q '^set \$prompt-' "$copy"; then
        echo "  $(basename "$copy") already has prompt colours"
        return 0
    fi
    for shipped in "$themes"/*/theme.conf /etc/skel/.config/sway/definitions.d/theme.light.conf_; do
        [ -f "$shipped" ] || continue
        if cmp -s "$copy" <(strip_prompt "$shipped"); then
            cp --backup -- "$shipped" "$copy"
            echo "  $(basename "$copy"): refreshed from $shipped"
            return 0
        fi
    done
    echo "  $(basename "$copy") was edited; leaving it, the prompt follows \$theme"
}

refresh "$dir/theme.conf"
refresh "$dir/theme.light.conf_"
