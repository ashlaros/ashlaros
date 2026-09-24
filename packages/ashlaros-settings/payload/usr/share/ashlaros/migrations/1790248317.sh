#!/usr/bin/env bash
#
# skel's sworkstyle config gained an icon for Telegram Desktop (app_id
# "org.telegram.desktop"), which sworkstyle's compiled defaults do not know
# under any name, so its workspace showed the generic fallback. /etc/skel
# is copied once at account creation, so a $HOME made before this keeps
# the old file. Same shape as 1790243356, which did this for zen.
set -uo pipefail

echo "Give Telegram a workspace icon in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# An entry the user wrote themselves wins.
if grep -q "^[[:space:]]*['\"]org\.telegram\.desktop['\"][[:space:]]*=" "$config"; then
    echo "  Telegram already has an entry, leaving it alone"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entry belongs"
    exit 0
fi

tmp=$(mktemp "${config}.XXXXXX") || exit 1
awk '{ print } /^\[matching\]/ { print "\x27org.telegram.desktop\x27 = \x27\xee\x88\x97\x27" }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added Telegram under [matching]"
