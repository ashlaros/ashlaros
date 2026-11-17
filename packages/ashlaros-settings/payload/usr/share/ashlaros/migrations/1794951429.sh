#!/usr/bin/env bash
#
# The herdr app window gets the waybar herdr module's glyph in its
# workspace name. sworkstyle matches app_id, class and title, and the
# window reports app_id "herdr-app", which neither upstream's compiled
# table nor a config made before skel carried the entry maps - so the
# workspace shows the fallback until this runs. Same shape as the
# sworkstyle half of 1790255648.
set -uo pipefail

echo "Show the herdr icon for the herdr app window"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
elif grep -q "^[[:space:]]*['\"]herdr-app['\"][[:space:]]*=" "$config"; then
    echo "  sworkstyle already has a herdr-app entry"
elif ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
else
    # md-robot (U+F06A9) as its UTF-8 bytes, so this file stays ASCII
    tmp=$(mktemp "${config}.XXXXXX") || exit 1
    awk -v line="'herdr-app' = '"$'\xf3\xb0\x9a\xa9'"'" \
        '{ print } /^\[matching\]/ { print line }' "$config" >"$tmp" ||
        { rm -f "$tmp"; exit 1; }
    chmod --reference="$config" "$tmp" 2>/dev/null || true
    mv -- "$tmp" "$config"
    echo "  added herdr-app under [matching]"
fi
