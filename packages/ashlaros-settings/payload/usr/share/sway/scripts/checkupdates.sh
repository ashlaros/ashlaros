#!/bin/sh
# pamac is Manjaro's; pacman-contrib's checkupdates does the same job on
# Arch, without touching the sync database a user's own pacman is using.

CACHE_FILE="/tmp/checkupdates-$USER"

# How long an answer is reused. waybar polls this every hour and the module
# is also signalled by hand, so the window only exists to stop `check` and
# `status` - which waybar runs back to back - syncing twice.
CACHE_SECONDS=30

# Ask the network, and only replace the cache if the answer is real.
#
# `checkupdates` runs its own `pacman -Sy` against a private database and
# dies with "Cannot fetch updates" when that fails - a mirror timing out, a
# laptop that has just woken, wifi not up yet. The previous version piped
# straight into `tee`, which truncates before the command runs: a failed
# sync did not just report nothing, it destroyed the last good answer, and
# 14 pending updates silently became 0 until the next successful poll.
refresh() {
    tmp="$CACHE_FILE.new"

    # checkupdates exits 2 when there is genuinely nothing to update and 1
    # when it could not find out. Only the first is an answer.
    out=$(checkupdates 2>/dev/null)
    case $? in
        0 | 2) ;;
        *) return 1 ;;
    esac

    # Everything below is a source the click action (topgrade) also
    # updates, counted so the badge and the button describe the same work.
    # Each is optional and each is allowed to fail on its own: they all
    # need the network, and one unreachable source must not blank a count
    # that was fetched successfully. A source that cannot answer
    # contributes nothing rather than zero.

    # The AUR half is whatever helper the user has.
    if [ -x "$(command -v yay)" ]; then
        out=$(printf '%s\n%s' "$out" "$(yay -Qua 2>/dev/null)")
    fi

    # One line per updatable ref. `remote-ls --updates` asks the remotes,
    # so it is the network call, not a local query.
    if [ -x "$(command -v flatpak)" ]; then
        out=$(printf '%s\n%s' "$out" \
            "$(flatpak remote-ls --updates --columns=application,version 2>/dev/null |
                sed 's/^/flatpak /')")
    fi

    # fwupdmgr exits 0 whether it found updates, found none, or could not
    # reach its daemon at all - "Failed to connect to daemon" and success
    # are indistinguishable by status. So the JSON is parsed instead, and
    # a payload carrying an Error rather than Devices contributes nothing.
    if [ -x "$(command -v fwupdmgr)" ] && [ -x "$(command -v jq)" ]; then
        out=$(printf '%s\n%s' "$out" \
            "$(fwupdmgr get-updates --json 2>/dev/null |
                jq -r '.Devices // [] | .[] | "firmware \(.Name) \(.Releases[0].Version // "")"' \
                    2>/dev/null)")
    fi

    # mise reports against the version the user asked for, so a pinned
    # tool is never "outdated" and a fuzzy one is only listed when the
    # pin itself can move. That is the right question for a badge: it
    # counts upgrades that would actually be taken.
    if [ -x "$(command -v mise)" ] && [ -x "$(command -v jq)" ]; then
        out=$(printf '%s\n%s' "$out" \
            "$(mise outdated --json 2>/dev/null |
                jq -r 'to_entries[] | "mise \(.key) \(.value.current // "") -> \(.value.latest // "")"' \
                    2>/dev/null)")
    fi

    # `grep -v` exits 1 when nothing survives the filter, which for a
    # machine that is genuinely up to date is the correct answer and not a
    # failure - so its status is deliberately not tested here. Writing the
    # temporary file and renaming is what makes the replacement atomic:
    # nothing truncates the cache that a concurrent reader may be using.
    printf '%s\n' "$out" | grep -v '^$' > "$tmp"
    mv "$tmp" "$CACHE_FILE"
}

get_updates() {
    if [ -f "$CACHE_FILE" ] &&
        [ $(($(date +%s) - $(stat -c %Y "$CACHE_FILE"))) -lt "$CACHE_SECONDS" ]; then
        cat "$CACHE_FILE"
        return 0
    fi

    # A stale cache is a better answer than no answer: it is what was true
    # the last time the network worked, which is the question the badge is
    # really answering. Returns non-zero when nothing at all is known, so
    # the caller can say so rather than showing a confident zero.
    if refresh; then
        cat "$CACHE_FILE"
        return 0
    fi

    [ -f "$CACHE_FILE" ] && cat "$CACHE_FILE"
    return 1
}

case $1'' in
'status')
    UPDATES=$(get_updates)
    FRESH=$?
    COUNT=$(echo "$UPDATES" | grep -cv '^$')
    TOOLTIP=$(echo "$UPDATES" | awk 1 ORS='\\n' | sed 's/\\n$//')
    # The badge counts pacman, AUR, flatpak, firmware and mise - the
    # sources that can say how much work they have without doing it.
    # Clicking runs topgrade, which has ~180 steps and no count-only mode,
    # so the remainder (cargo, git checkouts, shell plugins) is still work
    # the run may find and the badge cannot see. The tooltip says which
    # side of that line the number is on rather than letting it read as a
    # prediction of the run.
    TOOLTIP="$TOOLTIP\n\npacman, AUR, flatpak, firmware, mise. Updating runs topgrade's other steps too."
    if [ "$FRESH" -ne 0 ]; then
        # Say the number is old rather than presenting it as current. A
        # badge that silently stops moving is worse than one that admits
        # it cannot reach a mirror, because only the second is noticed.
        TOOLTIP="$TOOLTIP\nCould not reach a mirror; this count may be out of date."
        CLASS="stale"
    else
        CLASS="ok"
    fi
    jq -cn --arg count "$COUNT" --arg tooltip "$TOOLTIP" --arg class "$CLASS" \
        '{"text": $count, "tooltip": $tooltip, "class": $class}'
    ;;
'check')
    # Only false when there is nothing to show AND the answer is current.
    # A failed sync used to exit non-zero here, and waybar hides a module
    # whose exec-if fails - so the indicator vanished exactly when it had
    # something to say, which reads as "no updates" to anyone looking at
    # the bar.
    UPDATES=$(get_updates)
    FRESH=$?
    [ "$(echo "$UPDATES" | grep -cv '^$')" -gt 0 ] || [ "$FRESH" -ne 0 ]
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
