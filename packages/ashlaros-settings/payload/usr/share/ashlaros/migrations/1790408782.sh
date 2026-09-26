#!/usr/bin/env bash
#
# The keybinding help overlay learned to follow held keys (#89): eww.yuck
# gained the help-keys window and its watcher, eww.css imports the theme's
# colours from colors.css. /etc/skel is copied once at account creation, so
# a $HOME made before this still has the old two files - and help.sh opening
# a help-keys window that config does not define would fail quietly on
# every login, with the overlay never narrowing at all.
#
# Replaced only where the file is one we shipped, byte for byte. Every
# version that ever left skel is listed by its sha256: d916ff0, 807f402,
# eae42de and f013b8b for eww.yuck, and the one eww.css that never changed.
# A file matching none of them is the user's own, and is left alone with a
# note - overwriting a config someone wrote is not this script's call.
set -uo pipefail

echo "Help overlay: follow held keys, in the theme's colours (#89)"

dir="$HOME/.config/eww"
skel=/etc/skel/.config/eww

declare -A shipped=(
    [eww.yuck]="
        966982bdaf277784 820f765c11bc1fac fece629dab64786b 451108ed72b4c0a9"
    [eww.css]="2937819f0903c7b4"
)

# shipped: a version we shipped, or already the current one (a rerun)
state() {
    local name=$1 have
    [ -e "$dir/$name" ] || { echo absent; return; }
    cmp -s "$skel/$name" "$dir/$name" && { echo current; return; }
    have=$(sha256sum "$dir/$name" | cut -c1-16)
    case " ${shipped[$name]} " in
        *" $have "*) echo shipped ;;
        *) echo own ;;
    esac
}

install_one() {
    local name=$1
    mkdir -p "$dir"
    # in place rather than moved over: it may be a symlink into a dotfiles
    # repository, and replacing it would break the link
    cat -- "$skel/$name" > "$dir/$name" || return 1
    echo "  updated $name"
}

# The two are one change: the new eww.css styles classes only the new
# eww.yuck has, and imports colors.css the old one never needed. A yuck of
# the user's own keeps its stylesheet, whatever that stylesheet is.
if [ "$(state eww.yuck)" = own ]; then
    echo "  eww.yuck is your own, so neither file is changed; compare with $skel"
    exit 0
fi
for name in eww.yuck eww.css; do
    case $(state "$name") in
        current) ;;
        absent | shipped) install_one "$name" || exit 1 ;;
        own) echo "  $name is your own; compare it with $skel/$name" ;;
    esac
done
