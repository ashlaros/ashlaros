#!/bin/sh
export XDG_CONFIG_HOME=$HOME/.config

# vim rather than something larger: this has to work where $EDITOR is
# actually consumed - git commit, visudo, systemctl edit - which includes
# a TTY and an ssh session with no graphical anything. nano ships too, for
# whoever meets a modal editor by surprise.
export EDITOR=vim

# Most pure GTK3 apps use wayland by default, but some,
# such as Firefox, require the backend to be explicitly selected.
export MOZ_ENABLE_WAYLAND=1
export MOZ_DBUS_REMOTE=1

# No client-side decorations: sway draws a 1px border and no titlebar
# (etc/sway/modes/default), and a GTK headerbar inside that is a second
# decoration we asked not to have. QT_WAYLAND_DISABLE_WINDOWDECORATION
# below does the same job for Qt.
#
# The pair is the point. GTK_CSD is read by the preloaded library, not by
# GTK, so on its own it does nothing - which is what it did here for as
# long as it has been in this file. gtk-nocsd is what makes it mean
# something, and covers GTK4 and libadwaita as well as GTK3.
export GTK_CSD=0
# Guarded, because ld.so complains once per command when the library is
# missing - "cannot be preloaded (cannot open shared object file)" before
# every prompt and in the output of every script. gtk-nocsd is a hard
# dependency of this package, so normally it is there; someone who removes
# it should lose server-side decorations, not gain an error on every
# command they run.
if [ -e /usr/lib/libgtk-nocsd.so ]; then
	export LD_PRELOAD="/usr/lib/libgtk-nocsd.so${LD_PRELOAD:+:$LD_PRELOAD}"
fi

# qt wayland
export QT_QPA_PLATFORM="wayland"
# qt5ct rather than xdgdesktopportal: the portal theme sets no icon theme,
# so Qt fell back to hicolor - no folder or file-type icons anywhere. Qt5
# loads qt5ct's plugin under this name and Qt6 resolves it to qt6ct's;
# enable-qt-theme.sh writes the sway theme's icons and fonts into both.
# File dialogs still go through xdg-desktop-portal, to
# xdg-desktop-portal-lxqt (see FileChooser= in sway-portals.conf), because
# both configs say standard_dialogs=xdgdesktopportal.
export QT_QPA_PLATFORMTHEME=qt5ct
# Read by Qt5 and Qt6 alike, and independent of the platform theme. Kvantum
# picks its theme up from ~/.config/Kvantum/kvantum.kvconfig, which is what
# `kvantummanager --set` writes, so theme switching keeps working.
export QT_STYLE_OVERRIDE=kvantum
export QT_WAYLAND_DISABLE_WINDOWDECORATION="1"

# use xdg-desktop-portal for file dialogs in GTK apps
export GTK_USE_PORTAL=1

#Java XWayland blank screens fix
export _JAVA_AWT_WM_NONREPARENTING=1

# set default shell and terminal
export SHELL=/usr/bin/zsh
export TERMINAL_COMMAND=xdg-terminal-exec

# set ozone platform to wayland
export ELECTRON_OZONE_PLATFORM_HINT=wayland

# Disable hardware cursors. This might fix issues with
# disappearing cursors
if systemd-detect-virt -q; then
    # if the system is running inside a virtual machine, disable hardware cursors
    export WLR_NO_HARDWARE_CURSORS=1
fi

# Disable warnings by OpenCV
export OPENCV_LOG_LEVEL=ERROR

set -a
. "$HOME/.config/user-dirs.dirs"
set +a

if [ -n "$(ls "$HOME"/.config/profile.d 2>/dev/null)" ]; then
    for f in "$HOME"/.config/profile.d/*; do
        # shellcheck source=/dev/null
        . "$f"
    done
fi
