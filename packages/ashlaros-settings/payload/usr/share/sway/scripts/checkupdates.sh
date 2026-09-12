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
    COUNT=$(echo "$UPDATES" | grep -cv '^$')
    TOOLTIP=$(echo "$UPDATES" | awk 1 ORS='\\n' | sed 's/\\n$//')
    # The badge counts pacman and AUR, which is all that can be counted
    # cheaply. Clicking runs topgrade, which also updates flatpaks, cargo
    # binaries, firmware and git checkouts - so the tooltip says what the
    # number is rather than letting it read as a prediction of the run.
    TOOLTIP="$TOOLTIP\n\npacman and AUR. Updating also runs topgrade's other steps."
    jq -cn --arg count "$COUNT" --arg tooltip "$TOOLTIP" '{"text": $count, "tooltip": $tooltip}'
    ;;
'check')
    UPDATES=$(get_updates)
    [ "$(echo "$UPDATES" | grep -cv '^$')" -gt 0 ]
    exit $?
    ;;
'upgrade')
    # topgrade is a hard dependency of ashlaros-settings, so the four-branch
    # fallback chain this had was three dead branches: a guaranteed package
    # does not need a chain, and dead branches rot.
    #
    # The number beside this button counts pacman and AUR updates, while
    # topgrade also updates flatpaks, cargo binaries, firmware and git
    # checkouts. That mismatch is deliberate - topgrade has no count-only
    # mode, and never will for ~200 updaters - so the tooltip says so
    # rather than the badge pretending to predict the run.
    xdg-terminal-exec topgrade
    ;;
esac
