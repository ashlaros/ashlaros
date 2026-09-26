#!/usr/bin/env bash
#
# The launcher and every picker moved from rofi to fuzzel. Nothing a login
# runs writes ~/.config/rofi any more, so what the desktop left there is two
# files no program reads: rofi itself is no longer a dependency, and pacman
# removes it only if nothing else asks for it.
#
# Removed only where each is exactly what the desktop wrote. config.rasi was
# copied from the template once and never changed - its one version is
# `@import "ashlaros"`, by sha256. ashlaros.rasi was rewritten from the theme
# on every reload, so its colours are whichever theme was last active; it is
# matched by shape, the one template $rofi_theme ever had, with any colour.
# Anything else in the directory is the user's, and it stays - a rofi they
# still run is theirs to keep configuring.
set -uo pipefail

echo "Launcher: fuzzel replaces rofi; removing the desktop's rofi config"

dir="$HOME/.config/rofi"
[ -d "$dir" ] || { echo "  no ~/.config/rofi; nothing to do"; exit 0; }

config="$dir/config.rasi"
if [ -f "$config" ] && [ ! -L "$config" ] &&
    [ "$(sha256sum "$config" | cut -c1-16)" = ec53716dd5baa7f9 ]; then
    rm -f -- "$config" && echo "  removed config.rasi"
fi

theme="$dir/ashlaros.rasi"
# the desktop's shape, a line at a time, with a colour where each one went -
# awk rather than one multi-line grep, which is what failed on the real file
if [ -f "$theme" ] && [ ! -L "$theme" ] && awk '
    BEGIN {
        c = "#[0-9A-Fa-f]+;"
        n = split("^\\* \\{$|^lightbg: " c "$|^background: " c "$|^lightfg: " c "$|^foreground: " c "$|^\\}$|^window \\{$|^width: 25em;$|^\\}$", want, "|")
    }
    /^[[:space:]]*$/ { next }
    { i++; if (i > n || $0 !~ want[i]) bad = 1 }
    END { exit (bad || i != n) }
' "$theme"; then
    rm -f -- "$theme" && echo "  removed ashlaros.rasi"
fi

# the directory only if that left it empty
rmdir -- "$dir" 2>/dev/null && echo "  removed ~/.config/rofi" ||
    echo "  ~/.config/rofi holds files of your own; left in place"
exit 0
