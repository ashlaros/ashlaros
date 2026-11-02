#!/usr/bin/env bash
#
# skel's sworkstyle config gained an icon for Pear Desktop (formerly
# th-ch/youtube-music), app_id "com.github.th-ch.youtube-music". Upstream's
# compiled defaults have no entry for it under any name, so its workspace
# showed the generic fallback. /etc/skel is copied once at account
# creation, so a $HOME made before this keeps the old file. Same shape as
# 1792338383.
set -uo pipefail

echo "Give Pear Desktop (YouTube Music) a workspace icon in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# an entry the user wrote themselves wins
if grep -q "^[[:space:]]*['\"]com\.github\.th-ch\.youtube-music['\"][[:space:]]*=" "$config"; then
    echo "  com.github.th-ch.youtube-music already has an entry, leaving it alone"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
    exit 0
fi

# U+F16A (nf-fa-youtube_play) as its UTF-8 bytes, so this file stays ASCII
tmp=$(mktemp "${config}.XXXXXX") || exit 1
awk -v line="'com.github.th-ch.youtube-music' = '"$'\xef\x85\xaa'"'" '{ print } /^\[matching\]/ { print line }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added com.github.th-ch.youtube-music under [matching]"
