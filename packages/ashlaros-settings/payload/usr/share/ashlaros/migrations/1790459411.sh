#!/usr/bin/env bash
#
# The day/night pair ran the wrong way round. theme-toggle.sh names the
# stash for when it is shown - .light. is the day half, .dark. the night
# half - and its automatic switch applies `light` between sunrise and
# sunset. Settings -> Theme wrote the other way: the day theme live with
# the night theme stashed as .light., so with the switch on the night theme
# showed at noon.
#
# Fixed by renaming the stash to the other half's name, not by swapping
# contents: the theme on screen now stays on screen, and only which half it
# counts as changes. The foot halves are both stashes, so those swap.
#
# Only where the pair is visibly inverted: the half the toggle shows by day
# is a dark theme and the one it shows at night a light one, read from each
# file's own $gtk-color-scheme. Two dark themes, two light ones, or a file
# with no scheme could be anyone's deliberate choice, and are left alone
# with a note - Settings -> Theme sets a pair explicitly either way.
set -uo pipefail

echo "Theme: the day and night halves the right way round"

defs="$HOME/.config/sway/definitions.d"
foot="$HOME/.config/foot"
live="$defs/theme.conf"
day_stash="$defs/theme.light.conf_"
night_stash="$defs/theme.dark.conf_"

[ -f "$live" ] || { echo "  no theme.conf; nothing to do"; exit 0; }
if [ -f "$day_stash" ] && [ -f "$night_stash" ]; then
    echo "  both theme.light.conf_ and theme.dark.conf_ exist; leaving them alone"
    exit 0
fi

# which file is which half, as theme-toggle.sh reads them
if [ -f "$day_stash" ]; then
    day_file=$day_stash night_file=$live stash=$day_stash other=$night_stash
elif [ -f "$night_stash" ]; then
    day_file=$live night_file=$night_stash stash=$night_stash other=$day_stash
else
    echo "  no stashed half; nothing to do"
    exit 0
fi

scheme() { sed -n 's/^set \$gtk-color-scheme[[:space:]]*//p' "$1" | head -1; }
day_scheme=$(scheme "$day_file")
night_scheme=$(scheme "$night_file")

if [ "$day_scheme" != prefer-dark ] || [ "$night_scheme" != prefer-light ]; then
    echo "  the pair is not inverted (day: ${day_scheme:-no scheme}, night: ${night_scheme:-no scheme}); left alone"
    exit 0
fi

mv -- "$stash" "$other" || exit 1
echo "  $(basename "$stash") -> $(basename "$other")"

# foot: both halves are stashes, so the contents trade places; a missing
# half is left to merge_foot_themes, which needs both and says so
if [ -f "$foot/foot-theme.light.ini_" ] && [ -f "$foot/foot-theme.dark.ini_" ]; then
    tmp=$(mktemp "$foot/.swap.XXXXXX") || exit 1
    mv -- "$foot/foot-theme.light.ini_" "$tmp" &&
        mv -- "$foot/foot-theme.dark.ini_" "$foot/foot-theme.light.ini_" &&
        mv -- "$tmp" "$foot/foot-theme.dark.ini_" || exit 1
    echo "  swapped foot-theme.light.ini_ and foot-theme.dark.ini_"
    # the merged file foot reads, regenerated for the half that is live now
    [ -x /usr/share/sway/scripts/theme-toggle.sh ] &&
        /usr/share/sway/scripts/theme-toggle.sh merge-foot >/dev/null 2>&1
fi
exit 0
