#!/bin/sh
# ~/.config/eww/colors.css from the sway theme, for the keybinding help
# overlay (#89) - the waybar colors.css pattern: this file is overwritten on
# every theme switch, eww.css imports it and is the user's to edit.
#
# GTK's @define-color, which eww's CSS provider reads, rather than
# ${VARIABLE} substitution: eww substitutes environment variables only, and
# the theme's colours are sway variables, not the environment.
# Args: background-color text-color accent-color
set -u

dir="$HOME/.config/eww"
mkdir -p "$dir"

# Only on a change. eww watches its config directory and reloads on any
# .css write, which closes and reopens the window - on every sway reload,
# not only on a theme switch, without this.
new=$(cat <<CSS
/* Written by generate-help-style.sh from the sway theme; overwritten on a theme switch */
@define-color help_bg $1;
@define-color help_fg $2;
@define-color help_accent $3;
CSS
)
[ "$(cat "$dir/colors.css" 2>/dev/null)" = "$new" ] && exit 0
printf '%s\n' "$new" > "$dir/colors.css"
