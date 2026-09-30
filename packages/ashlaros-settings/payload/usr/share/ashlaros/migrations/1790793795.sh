#!/usr/bin/env bash
#
# The held-keys overlay follows the focused output: help-keys became one
# window per output, taking its index as an argument, and help.sh opens it
# with --arg screen=N. /etc/skel is copied once at account creation, so a
# $HOME made before this has the help-keys that takes no argument - eww
# refuses to open it with one, and the held keys would show nowhere at all.
#
# Replaced only where the file is one we shipped, byte for byte: every
# eww.yuck that ever left skel is listed by its sha256. A file matching none
# of them is the user's own, and is left alone with a note.
set -uo pipefail

echo "Help overlay: held keys on the focused output"

dst="$HOME/.config/eww/eww.yuck"
src=/etc/skel/.config/eww/eww.yuck

# d916ff0, 807f402, eae42de, f013b8b, ef4c219
shipped=" 966982bdaf277784 820f765c11bc1fac fece629dab64786b 451108ed72b4c0a9 d4ea6d6dc1f66e55 "

[ -f "$src" ] || exit 0
# absent is 1789563375.sh's to seed, and the autostart guard skips the
# overlay without it
[ -e "$dst" ] || exit 0
cmp -s "$src" "$dst" && exit 0

have=$(sha256sum "$dst" | cut -c1-16)
case "$shipped" in
    *" $have "*) ;;
    *)
        echo "  eww.yuck is your own; compare it with $src"
        exit 0
        ;;
esac

# in place rather than moved over: it may be a symlink into a dotfiles
# repository, and replacing it would break the link
cat -- "$src" > "$dst" || exit 1
echo "  updated eww.yuck"
