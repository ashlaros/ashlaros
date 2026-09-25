#!/usr/bin/env bash
#
# Qt apps drew no folder or file-type icons. .profile named
# xdgdesktopportal as the Qt platform theme, which sets no icon theme, so
# Qt fell back to hicolor; the icon_theme in skel's qt5ct.conf and
# qt6ct.conf was never read. skel's .profile now names qt5ct, and
# enable-qt-theme.sh writes the sway theme's icons, fonts and portal file
# dialogs into both configs on every reload - but .profile is per-user.
#
# The catppuccin themes named their GTK theme as the icon theme, which no
# icon theme is called; they now name Papirus. A copy of one in
# definitions.d keeps the old line, so that is fixed here too.
set -uo pipefail

echo "Give Qt apps the desktop's icon theme"

# Written in place rather than moved over: these may be symlinks into a
# dotfiles repository, and replacing them would break the link.
rewrite() {
    local file=$1 script=$2 tmp
    tmp=$(mktemp) || return 1
    sed "$script" "$file" >"$tmp" || { rm -f "$tmp"; return 1; }
    cat "$tmp" >"$file" || { rm -f "$tmp"; return 1; }
    rm -f "$tmp"
}

profile="$HOME/.profile"
# only the value we shipped; a platform theme someone chose stays
if [ -f "$profile" ] && grep -q '^export QT_QPA_PLATFORMTHEME=xdgdesktopportal$' "$profile"; then
    rewrite "$profile" 's/^export QT_QPA_PLATFORMTHEME=xdgdesktopportal$/export QT_QPA_PLATFORMTHEME=qt5ct/' || exit 1
    echo "  ~/.profile: QT_QPA_PLATFORMTHEME=qt5ct"
    # Said rather than silently true: greetd read .profile long before
    # migrations run, and a login shell cannot be re-sourced into a session
    # that is already running.
    echo "  Qt apps get their icons from the next login."
else
    echo "  ~/.profile does not name xdgdesktopportal; leaving it alone"
fi

defs="${XDG_CONFIG_HOME:-$HOME/.config}/sway/definitions.d"
for conf in "$defs"/theme.conf "$defs"/theme.light.conf_; do
    [ -f "$conf" ] || continue
    if grep -q '^set \$icon-theme catppuccin-latte-blue-standard+default$' "$conf"; then
        rewrite "$conf" 's/^set \$icon-theme catppuccin-latte-blue-standard+default$/set $icon-theme Papirus-Light/' || exit 1
        echo "  $conf: icon theme Papirus-Light"
    elif grep -q '^set \$icon-theme catppuccin-[a-z]*-blue-standard+default$' "$conf"; then
        rewrite "$conf" 's/^set \$icon-theme catppuccin-[a-z]*-blue-standard+default$/set $icon-theme Papirus-Dark/' || exit 1
        echo "  $conf: icon theme Papirus-Dark"
    fi
done
