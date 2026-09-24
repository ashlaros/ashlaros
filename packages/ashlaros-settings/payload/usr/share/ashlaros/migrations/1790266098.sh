#!/usr/bin/env bash
#
# skel's sworkstyle config gained an icon for "foot", the app_id of a
# standalone foot (not a foot-server client). Upstream's compiled defaults
# map it to nf-fa-terminal, so beside footclient's nf-dev-terminal the
# same terminal showed two icons. /etc/skel is copied once at account
# creation, so a $HOME made before this keeps the old file. Same shape as
# 1790254490.
set -uo pipefail

echo "Give a standalone foot the terminal icon in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# an entry the user wrote themselves wins
if grep -q "^[[:space:]]*['\"]foot['\"][[:space:]]*=" "$config"; then
    echo "  foot already has an entry, leaving it alone"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
    exit 0
fi

# U+E795 (nf-dev-terminal) as its UTF-8 bytes, so this file stays ASCII
tmp=$(mktemp "${config}.XXXXXX") || exit 1
awk -v line="'foot' = '"$'\xee\x9e\x95'"'" '{ print } /^\[matching\]/ { print line }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added foot under [matching]"
