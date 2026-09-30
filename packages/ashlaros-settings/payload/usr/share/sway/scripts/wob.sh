#!/usr/bin/env sh
# wrapper script for wob — https://github.com/francma/wob/wiki/wob-wrapper-script
# $1 - accent color   $2 - background color   $3 - new value | --refresh
#
# Theme colors are kept in a managed file that is regenerated on every theme
# switch; the user's ~/.config/wob.ini is seeded once and then never touched.
# The config handed to wob is the managed colors followed by the user file, so
# anything set in ~/.config/wob.ini overrides the theme (same model as waybar's
# colors.css/style.css split).
#
# wob itself is wob.socket's: systemd holds the FIFO and starts wob.service
# on the first value written, and stops it with the session - see
# /etc/systemd/user/wob.service.d. This only writes values and the config.

MARKER="# managed by ashlaros"

wob_pipe="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/wob.sock"

user_ini=~/.config/wob.ini
colors_ini=~/.config/wob.colors.ini
# the path wob.service.d passes to wob -c
effective_ini=~/.cache/wob.ini

to_wob_color() {
    # wob expects RRGGBB[AA]; sway themes provide #RRGGBB
    hex="${1#\#}"
    echo "${hex}FF"
}

# Theme-managed colors only — safe to overwrite on every theme switch.
refresh_colors() {
    {
        echo "$MARKER — regenerated on every theme switch, edits here are lost."
        echo "# Put overrides in ~/.config/wob.ini instead."
        echo "border_color = $(to_wob_color "$1")"
        echo "bar_color = $(to_wob_color "$1")"
        echo "background_color = $(to_wob_color "$2")"
    } >"$colors_ini"
}

# Seed the user config once, then leave it alone.
seed_user_ini() {
    # Migrate the legacy auto-generated wob.ini (no marker, baked-in colors) out
    # of the way so its hard-coded colors stop shadowing the managed theme.
    if [ -f "$user_ini" ] && ! grep -qF "$MARKER" "$user_ini" && grep -qF "bar_color" "$user_ini"; then
        mv "$user_ini" "$user_ini.bak"
    fi
    [ -f "$user_ini" ] && return
    {
        echo "$MARKER seeded this file once; it is now yours to edit freely."
        echo "# Colors come from ~/.config/wob.colors.ini (theme-managed);"
        echo "# anything set here overrides the theme."
        echo "anchor = top center"
        echo "margin = 20"
    } >"$user_ini"
}

# Managed colors first so user settings in wob.ini take precedence.
build_effective_ini() {
    cat "$colors_ini" "$user_ini" >"$effective_ini"
}

seed_user_ini
if [ ! -f "$colors_ini" ] || [ "$3" = "--refresh" ]; then
    refresh_colors "$1" "$2"
fi
build_effective_ini

# On a theme refresh, restart wob so the new colors take effect. try-: one
# that is not running reads the new file when it next starts.
if [ "$3" = "--refresh" ]; then
    systemctl --user try-restart wob.service
    exit 0
fi

# Without the socket - no user manager, or wob.socket not enabled yet -
# there is no reader, and a write here would create a regular file where
# the socket's FIFO has to go.
[ -p "$wob_pipe" ] || exit 0
if [ -n "$3" ]; then
    echo "$3" >"$wob_pipe"
else
    cat >"$wob_pipe"
fi
