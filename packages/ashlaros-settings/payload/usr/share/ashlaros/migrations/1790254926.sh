#!/usr/bin/env bash
#
# skel's sworkstyle config now prefers nf-fae over nf-fa: Telegram's icon is
# fae-telegram (U+E217) instead of fa-telegram (U+F2C6), which 1790248317
# wrote before it changed. The other fa icons have no fae counterpart.
#
# Only a line that still carries exactly the fa icon we wrote is changed; an
# entry the user changed to anything else is theirs and stays.
set -uo pipefail

echo "Use the nf-fae Telegram icon in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# both icons as UTF-8 bytes, so this file stays ASCII
from="'org.telegram.desktop' = '"$'\xef\x8b\x86'"'"
to="'org.telegram.desktop' = '"$'\xee\x88\x97'"'"

if ! grep -qxF "$from" "$config"; then
    echo "  Telegram does not have the old icon, leaving it alone"
    exit 0
fi

sed -i "s|^${from//./\\.}\$|$to|" "$config" || exit 1
echo "  org.telegram.desktop: nf-fa icon replaced with nf-fae"
