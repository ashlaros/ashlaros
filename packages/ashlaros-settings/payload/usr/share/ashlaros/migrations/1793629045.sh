#!/usr/bin/env bash
#
# skel's sworkstyle config gained an icon for Teams for Linux, app_id
# "teams-for-linux". Upstream's compiled defaults have no entry for it
# under any name, so its workspace showed the generic fallback. /etc/skel
# is copied once at account creation, so a $HOME made before this keeps
# the old file. Same shape as 1793610388.
set -uo pipefail

echo "Give Teams for Linux a workspace icon in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# an entry the user wrote themselves wins
if grep -q "^[[:space:]]*['\"]teams-for-linux['\"][[:space:]]*=" "$config"; then
    echo "  teams-for-linux already has an entry, leaving it alone"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
    exit 0
fi

# U+F02BB (nf-md-microsoft_teams) as its UTF-8 bytes, so this file stays ASCII
tmp=$(mktemp "${config}.XXXXXX") || exit 1
awk -v line="'teams-for-linux' = '"$'\xf3\xb0\x8a\xbb'"'" '{ print } /^\[matching\]/ { print line }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added teams-for-linux under [matching]"
