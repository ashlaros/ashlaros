#!/bin/sh
# pamac is Manjaro's; pacman-contrib's checkupdates does the same job on
# Arch, without touching the sync database a user's own pacman is using.

get_updates() {
    CACHE_FILE="/tmp/checkupdates-$USER"
    if [ -f "$CACHE_FILE" ] && [ $(($(date +%s) - $(stat -c %Y "$CACHE_FILE"))) -lt 30 ]; then
        cat "$CACHE_FILE"
    else
        # checkupdates exits 2 when there is nothing to do, which is not an
        # error here; the AUR half is whatever helper the user has
        { checkupdates; [ -x "$(command -v yay)" ] && yay -Qua 2>/dev/null; } |
            tee "$CACHE_FILE"
    fi
}

case $1'' in
'status')
    UPDATES=$(get_updates)
    COUNT=$(echo "$UPDATES" | grep -v '^$' | wc -l)
    TOOLTIP=$(echo "$UPDATES" | awk 1 ORS='\\n' | sed 's/\\n$//')
    jq -cn --arg count "$COUNT" --arg tooltip "$TOOLTIP" '{"text": $count, "tooltip": $tooltip}'
    ;;
'check')
    UPDATES=$(get_updates)
    [ $(echo "$UPDATES" | grep -v '^$' | wc -l) -gt 0 ]
    exit $?
    ;;
'upgrade')
    if [ -x "$(command -v pacseek)" ]; then
        xdg-terminal-exec pacseek -u
    elif [ -x "$(command -v topgrade)" ]; then
        xdg-terminal-exec topgrade
    elif [ -x "$(command -v yay)" ]; then
        xdg-terminal-exec yay -Syu
    else
        xdg-terminal-exec sudo pacman -Syu
    fi
    ;;
esac
