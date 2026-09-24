#!/usr/bin/env bash
#
# skel's sworkstyle config gained an icon for "slack", Slack's Wayland
# app_id. Upstream's compiled defaults match only the X11 class 'Slack',
# and matching is exact, so its workspace showed the generic fallback.
# /etc/skel is copied once at account creation, so a $HOME made before
# this keeps the old file. Same shape as 1790248549.
set -uo pipefail

echo "Give Slack a workspace icon in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# an entry the user wrote themselves wins
if grep -q "^[[:space:]]*['\"]slack['\"][[:space:]]*=" "$config"; then
    echo "  slack already has an entry, leaving it alone"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
    exit 0
fi

# U+E8A4 (nf-dev-slack) as its UTF-8 bytes, so this file stays ASCII
tmp=$(mktemp "${config}.XXXXXX") || exit 1
awk -v line="'slack' = '"$'\xee\xa2\xa4'"'" '{ print } /^\[matching\]/ { print line }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added slack under [matching]"
