#!/usr/bin/env bash
#
# aee23a9 settled the stashed theme on dark/light. A $HOME created before
# it keeps theme.night.conf_, which theme-toggle.sh never reads, so
# waybar's exec-if fails and the theme module does not appear at all - the
# toggle is unreachable rather than visibly broken (#18).
#
# foot needs more than a rename: merge_foot_themes wants a .dark. and a
# .light. half and returns 1 without both, so the old name is moved and the
# dark half is seeded from the shipped skel if it is missing.
set -uo pipefail

echo "Rename the stashed theme to the dark/light spelling (#18)"

sway_dir="$HOME/.config/sway/definitions.d"
foot_dir="$HOME/.config/foot"

# Renaming onto an existing file would destroy whichever the user is
# actually using, so every move here refuses a target that exists. That
# also makes a fresh install a no-op: the new names are already there.
move_once() {
    [ -f "$1" ] || return 0
    if [ -e "$2" ]; then
        echo "  $(basename "$2") already exists, leaving $(basename "$1") alone"
        return 0
    fi
    mv -- "$1" "$2"
    echo "  $(basename "$1") -> $(basename "$2")"
}

move_once "$sway_dir/theme.night.conf_" "$sway_dir/theme.light.conf_"
move_once "$foot_dir/foot-theme.night.ini_" "$foot_dir/foot-theme.light.ini_"

# The dark half is new in that commit rather than renamed, so an old $HOME
# has no copy of it at all. Seeded from skel, and only when absent: a user
# who wrote their own must keep it.
skel_dark="/etc/skel/.config/foot/foot-theme.dark.ini_"
user_dark="$foot_dir/foot-theme.dark.ini_"
if [ ! -e "$user_dark" ] && [ -f "$skel_dark" ] && [ -d "$foot_dir" ]; then
    cp -- "$skel_dark" "$user_dark"
    echo "  seeded foot-theme.dark.ini_ from skel"
fi

# The merged file theme-toggle.sh actually reads is generated from the two
# halves; regenerate it now that both exist, so the change is visible in
# this session rather than after the next toggle.
if [ -x /usr/share/sway/scripts/theme-toggle.sh ] &&
    [ -f "$foot_dir/foot-theme.dark.ini_" ] &&
    [ -f "$foot_dir/foot-theme.light.ini_" ]; then
    /usr/share/sway/scripts/theme-toggle.sh merge-foot >/dev/null 2>&1 || true
fi
