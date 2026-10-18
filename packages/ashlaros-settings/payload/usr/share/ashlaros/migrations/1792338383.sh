#!/usr/bin/env bash
#
# skel's sworkstyle config gained an icon for "vesktop", Vesktop's app_id.
# Upstream's compiled defaults map it to U+F392, Font Awesome 5's Discord
# codepoint, which Nerd Fonts does not carry, so its workspace showed a
# missing glyph. /etc/skel is copied once at account creation, so a $HOME
# made before this keeps the old file. Same shape as 1790266098.
set -uo pipefail

echo "Give Vesktop a workspace icon the font has in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# an entry the user wrote themselves wins
if grep -q "^[[:space:]]*['\"]vesktop['\"][[:space:]]*=" "$config"; then
    echo "  vesktop already has an entry, leaving it alone"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
    exit 0
fi

# U+F1FF (nf-fa-discord) as its UTF-8 bytes, so this file stays ASCII
tmp=$(mktemp "${config}.XXXXXX") || exit 1
awk -v line="'vesktop' = '"$'\xef\x87\xbf'"'" '{ print } /^\[matching\]/ { print line }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added vesktop under [matching]"
