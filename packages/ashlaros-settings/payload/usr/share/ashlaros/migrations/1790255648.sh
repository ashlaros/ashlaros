#!/usr/bin/env bash
#
# A foot window running tmux, zellij or herdr now gets the dev-tmux icon in
# its workspace name. Two halves, both per-user and both skel, so a $HOME
# made before this has neither:
#
#   ~/.config/zsh/.zshrc   the preexec/precmd hook that sets the window's
#                          app_id to "terminal-multiplexer" through foot's
#                          OSC 176, and resets it at the next prompt
#   sworkstyle config      'terminal-multiplexer' = dev-tmux (U+E94C)
#
# Each half is added only where it is missing, and the zshrc block only to
# a .zshrc that still sources /etc/zsh/zshrc - a file rewritten into
# something else is the user's.
set -uo pipefail

echo "Show the tmux icon for terminals running a multiplexer"

zshrc="${ZDOTDIR:-$HOME/.config/zsh}/.zshrc"
sworkstyle="$HOME/.config/sworkstyle/config.toml"
skel_zshrc=/etc/skel/.config/zsh/.zshrc

if [ ! -f "$zshrc" ]; then
    echo "  no .zshrc; nothing to hook"
elif grep -q '_ashlaros_mux_appid' "$zshrc"; then
    echo "  .zshrc already has the multiplexer hook"
elif ! grep -q '^source /etc/zsh/zshrc' "$zshrc"; then
    echo "  .zshrc is not the shipped one; leaving it alone"
elif [ ! -f "$skel_zshrc" ]; then
    echo "  $skel_zshrc is missing"
    exit 1
else
    # The block exactly as skel carries it: from its first comment line to
    # the blank line after its closing fi.
    block=$(awk '
        /^# A multiplexer in a foot window marks the window/ { f = 1 }
        f { print }
        f && /^fi$/ { exit }' "$skel_zshrc")
    if [ -z "$block" ]; then
        echo "  the shipped .zshrc has no multiplexer block"
        exit 1
    fi
    # before the user-defined overrides, where skel has it, so a user's own
    # config.d can still undo it; appended if that line is gone
    tmp=$(mktemp "${zshrc}.XXXXXX") || exit 1
    if grep -q '^# user-defined overrides$' "$zshrc"; then
        # through the environment, not -v: -v processes backslash escapes,
        # and the block is made of them
        BLOCK=$block awk '
            /^# user-defined overrides$/ && !done { print ENVIRON["BLOCK"]; print ""; done = 1 }
            { print }' "$zshrc" >"$tmp"
    else
        { cat "$zshrc"; printf '\n%s\n' "$block"; } >"$tmp"
    fi || { rm -f "$tmp"; exit 1; }
    chmod --reference="$zshrc" "$tmp" 2>/dev/null || true
    mv -- "$tmp" "$zshrc"
    echo "  added the multiplexer hook to .zshrc"
fi

if [ ! -f "$sworkstyle" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
elif grep -q "^[[:space:]]*['\"]terminal-multiplexer['\"][[:space:]]*=" "$sworkstyle"; then
    echo "  sworkstyle already has a terminal-multiplexer entry"
elif ! grep -q '^\[matching\]' "$sworkstyle"; then
    echo "  no [matching] table; not guessing where the entry belongs"
else
    # U+E94C as its UTF-8 bytes, so this file stays ASCII
    tmp=$(mktemp "${sworkstyle}.XXXXXX") || exit 1
    awk -v line="'terminal-multiplexer' = '"$'\xee\xa5\x8c'"'" \
        '{ print } /^\[matching\]/ { print line }' "$sworkstyle" >"$tmp" ||
        { rm -f "$tmp"; exit 1; }
    chmod --reference="$sworkstyle" "$tmp" 2>/dev/null || true
    mv -- "$tmp" "$sworkstyle"
    echo "  added terminal-multiplexer under [matching]"
fi
