#!/usr/bin/env bash
#
# skel's sworkstyle config gained an icon for "com.microsoft.VSCode", the
# Wayland app_id of Microsoft's VS Code build. Upstream's compiled defaults
# know only 'Code' and 'code-oss', and matching is exact, so its workspace
# showed the generic fallback. /etc/skel is copied once at account
# creation, so a $HOME made before this keeps the old file. Same shape as
# 1790254490.
set -uo pipefail

echo "Give VS Code a workspace icon in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# an entry the user wrote themselves wins
if grep -q "^[[:space:]]*['\"]com\.microsoft\.VSCode['\"][[:space:]]*=" "$config"; then
    echo "  com.microsoft.VSCode already has an entry, leaving it alone"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
    exit 0
fi

# U+E8DA (nf-dev-vscode) as its UTF-8 bytes, so this file stays ASCII
tmp=$(mktemp "${config}.XXXXXX") || exit 1
awk -v line="'com.microsoft.VSCode' = '"$'\xee\xa3\x9a'"'" '{ print } /^\[matching\]/ { print line }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added com.microsoft.VSCode under [matching]"
