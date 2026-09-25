#!/bin/bash
set -u

# The Qt half of what gsettings does for GTK. Qt apps read their icon theme
# and fonts from the platform theme, and .profile names qt5ct: Qt5 loads
# qt5ct's plugin and reads qt5ct.conf, Qt6 resolves the same name to
# qt6ct's and reads qt6ct.conf. The portal's file dialog runs under the
# lxqt platform theme instead, which reads lxqt.conf - and falls back to
# oxygen, which nothing installs, so without this it draws no icons either.
#
# All three watch their file, so running apps follow a theme switch.

ICON_THEME=$1
GUI_FONT=$2
TERM_FONT=$3

config="${XDG_CONFIG_HOME:-$HOME/.config}"

# sway's fonts are "Family Size"; $term-font carries no size, so it takes
# the GUI one. Quoted, because QSettings would split "Family,Size" into a
# list and QFont reads nothing from a list.
gui_size=${GUI_FONT##* }
gui_family=${GUI_FONT% *}
case $gui_size in
'' | *[!0-9]*)
    gui_size=11
    gui_family=$GUI_FONT
    ;;
esac
term_size=${TERM_FONT##* }
term_family=${TERM_FONT% *}
case $term_size in
'' | *[!0-9]*)
    term_size=$gui_size
    term_family=$TERM_FONT
    ;;
esac

# key=value under [section], replacing the key where it is and adding the
# section where it is not; with keep=1 a key that is already there stays.
# Written only on a change: every write makes each running Qt app reload
# its settings, and this runs on every sway reload. In place rather than
# moved over, so a config symlinked from a dotfiles repository stays one.
set_key() {
    local file=$1 section=$2 key=$3 value=$4 keep=${5:-0} tmp
    mkdir -p "$(dirname "$file")"
    [ -f "$file" ] || : >"$file"
    tmp=$(mktemp) || return 1
    awk -v s="[$section]" -v k="$key" -v v="$value" -v keep="$keep" '
        function flush() { for (; blank > 0; blank--) print "" }
        $0 == s { insec = 1; print; next }
        insec && /^\[/ { if (!done) print k "=" v; done = 1; insec = 0 }
        insec && /^$/ { blank++; next }
        insec && index($0, k "=") == 1 {
            flush()
            if (!done) print (keep ? $0 : k "=" v)
            done = 1
            next
        }
        { flush(); print }
        END {
            if (!done) { if (!insec) { if (NR) print ""; print s }; print k "=" v }
            flush()
        }
    ' "$file" >"$tmp" || { rm -f "$tmp"; return 1; }
    cmp -s "$tmp" "$file" || cat "$tmp" >"$file"
    rm -f "$tmp"
}

for ct in qt5ct qt6ct; do
    set_key "$config/$ct/$ct.conf" Appearance icon_theme "$ICON_THEME"
    # File dialogs through the portal, as they went before qt5ct was the
    # platform theme. A default, not the theme's: someone who picked
    # another dialog in qt5ct keeps it.
    set_key "$config/$ct/$ct.conf" Appearance standard_dialogs xdgdesktopportal 1
    set_key "$config/$ct/$ct.conf" Fonts general "\"$gui_family,$gui_size\""
    set_key "$config/$ct/$ct.conf" Fonts fixed "\"$term_family,$term_size\""
done
set_key "$config/lxqt/lxqt.conf" General icon_theme "$ICON_THEME"
