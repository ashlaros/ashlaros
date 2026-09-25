#!/usr/bin/env bash
#
# pcmanfm-qt's archiver was file-roller, which nothing installs: its own
# built-in default, and the one skel's libfm.conf named. So "Extract Here"
# and a double-clicked .zip ran a program that is not there. The package
# now ships lxqt-archiver and names it in /etc/xdg - but pcmanfm-qt writes
# its whole settings.conf, Archiver=file-roller included, into the user's
# profile on first exit, and that copy wins over /etc/xdg from then on.
set -uo pipefail

echo "Point the file manager at lxqt-archiver"

config="${XDG_CONFIG_HOME:-$HOME/.config}"
changed=0

# every profile, not only "default": pcmanfm-qt --profile makes others
for settings in "$config"/pcmanfm-qt/*/settings.conf; do
    [ -f "$settings" ] || continue
    # only the value we know is broken; an archiver someone chose stays
    if grep -q '^Archiver=file-roller$' "$settings"; then
        sed -i 's/^Archiver=file-roller$/Archiver=lxqt-archiver/' "$settings"
        echo "  $settings"
        changed=1
    fi
done

libfm="$config/libfm/libfm.conf"
if [ -f "$libfm" ] && grep -q '^archiver=file-roller$' "$libfm"; then
    sed -i 's/^archiver=file-roller$/archiver=lxqt-archiver/' "$libfm"
    echo "  $libfm"
    changed=1
fi

[ "$changed" = 1 ] || echo "  nothing named file-roller; leaving the archiver alone"
