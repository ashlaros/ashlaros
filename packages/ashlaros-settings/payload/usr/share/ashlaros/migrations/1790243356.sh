#!/usr/bin/env bash
#
# skel's sworkstyle config gained an icon for zen, the browser every
# desktop ships (app_id "zen"); sworkstyle's compiled defaults know firefox
# but not zen, so its workspace showed the generic fallback. /etc/skel is
# copied once at account creation, so a $HOME made before this keeps the
# old file.
set -uo pipefail

echo "Give zen-browser a workspace icon in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# A zen entry the user wrote themselves wins.
if grep -q "^[[:space:]]*['\"]zen['\"][[:space:]]*=" "$config"; then
    echo "  zen already has an entry, leaving it alone"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
    exit 0
fi

tmp=$(mktemp "${config}.XXXXXX") || exit 1
awk '{ print } /^\[matching\]/ { print "\x27zen\x27 = \x27\xf3\xb0\x96\x9f\x27" }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added zen under [matching]"
