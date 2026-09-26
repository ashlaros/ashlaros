#!/bin/sh
# ~/.config/fuzzel/colors.ini from the sway theme, for every menu the desktop
# opens - the launcher, the clipboard, the window switcher, the pickers.
#
# The waybar colors.css pattern: this file is overwritten on every theme
# switch, fuzzel.ini includes it and is the user's to edit. fuzzel has no
# stylesheet and no variables, so the theme reaches it as a config file it
# reads on every start; nothing is running to be told about the switch.
#
# The same three colours every theme names the same way, and the theme's
# own GUI font and icon theme. $colorN would not do - see the note beside
# $generate_starship_config in etc/sway/definitions.
# Args: background-color text-color accent-color gui-font icon-theme
set -u

# #rrggbb or #rgb, as the themes spell them, to fuzzel's rrggbbaa
rgba() {
    c=${1#\#}
    if [ ${#c} = 3 ]; then
        c=$(printf '%s' "$c" | sed 's/./&&/g')
    fi
    printf '%sff' "$c"
}

# "Roboto 11" to fontconfig's "Roboto:size=11"; a font with no trailing size
# is passed through
font() {
    case $1 in
    *[!0-9.]" "[0-9]*) printf '%s:size=%s' "${1% *}" "${1##* }" ;;
    *) printf '%s' "$1" ;;
    esac
}

bg=$(rgba "$1")
fg=$(rgba "$2")
accent=$(rgba "$3")

dir="$HOME/.config/fuzzel"
mkdir -p "$dir"

# Only on a change, so a sway reload that switched nothing writes nothing.
new=$(cat <<INI
# Written by generate-fuzzel-config.sh from the sway theme; overwritten on a
# theme switch. Change fuzzel.ini instead: it includes this file first.
[main]
font=$(font "$4")
icon-theme=$5

[colors]
background=$bg
text=$fg
input=$fg
prompt=$accent
placeholder=${fg%ff}99
match=$accent
selection=$accent
selection-text=$bg
selection-match=$bg
counter=${fg%ff}99
border=$accent
INI
)
[ "$(cat "$dir/colors.ini" 2>/dev/null)" = "$new" ] ||
    printf '%s\n' "$new" > "$dir/colors.ini"

# The user's own file, once: the theme, then the desktop's defaults, then
# whatever they add. Written here rather than shipped in skel so a $HOME
# made before fuzzel gets one too - the waybar.sh style.css pattern.
[ -f "$dir/fuzzel.ini" ] || cat > "$dir/fuzzel.ini" <<'INI'
# fuzzel's config, and yours to edit. colors.ini is written from the sway
# theme on every switch; the template holds the desktop's defaults. Both are
# included first, so a setting below overrides either.
include=~/.config/fuzzel/colors.ini
include=/usr/share/sway/templates/fuzzel/fuzzel.ini
INI
exit 0
