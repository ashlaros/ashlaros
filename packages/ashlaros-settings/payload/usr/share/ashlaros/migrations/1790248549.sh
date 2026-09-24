#!/usr/bin/env bash
#
# skel's sworkstyle config gained icons for two app_ids its compiled
# defaults miss: "footclient", which every terminal here is (upstream
# knows only 'foot'), and "signal", Signal Desktop on Wayland (upstream
# knows only the X11 class 'Signal', and matching is exact). Both showed
# the generic fallback. /etc/skel is copied once at account creation, so a
# $HOME made before this keeps the old file. Same shape as 1790243356.
set -uo pipefail

echo "Give the foot terminal and Signal workspace icons in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entries belong"
    exit 0
fi

# app_id, then the icon as the UTF-8 bytes of U+E795 or U+F075, spelled as
# $'\x..' escapes so this file stays ASCII
add() {
    local app=$1 icon=$2 tmp
    # an entry the user wrote themselves wins
    if grep -q "^[[:space:]]*['\"]${app//./\\.}['\"][[:space:]]*=" "$config"; then
        echo "  $app already has an entry, leaving it alone"
        return 0
    fi
    tmp=$(mktemp "${config}.XXXXXX") || return 1
    awk -v line="'$app' = '$icon'" '{ print } /^\[matching\]/ { print line }' \
        "$config" >"$tmp" || { rm -f "$tmp"; return 1; }
    chmod --reference="$config" "$tmp" 2>/dev/null || true
    mv -- "$tmp" "$config"
    echo "  added $app under [matching]"
}

add footclient $'\xee\x9e\x95' || exit 1
add signal $'\xef\x81\xb5' || exit 1
