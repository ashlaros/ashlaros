#!/usr/bin/env bash
#
# 485149a added `prompt off` to the shipped .zshrc. Without it grml's
# prompt_grml_precmd rebuilds PROMPT after every command and silently
# clobbers what `starship init zsh` set, so the shell shows grml's
# user@host prompt and the AshlarOS mark never appears. A $HOME created
# before that commit keeps the old file and keeps the wrong prompt.
#
# Inserted rather than copied from skel: .zshrc is a file people edit, and
# replacing it wholesale would take their aliases with it.
set -uo pipefail

echo "Turn grml's prompt off so starship's survives (#106-era prompt fix)"

zshrc="${ZDOTDIR:-$HOME/.config/zsh}/.zshrc"

[ -f "$zshrc" ] || {
    echo "  no ~/.config/zsh/.zshrc; nothing to migrate"
    exit 0
}

# Already correct - a fresh $HOME, or a second run. Both are no-ops.
if grep -qx 'prompt off' "$zshrc"; then
    echo "  already set"
    exit 0
fi

# Only where starship is actually initialised. A user who removed that
# line has chosen their own prompt, and `prompt off` would leave them with
# no prompt at all rather than the one they picked.
starship_line=$(grep -n 'starship init zsh' "$zshrc" | head -1 | cut -d: -f1)
if [ -z "$starship_line" ]; then
    echo "  no starship init in this .zshrc, leaving the prompt alone"
    exit 0
fi

# Written beside the file and moved into place, so an interrupted run
# cannot leave a truncated .zshrc - which is a shell that does not start.
tmp=$(mktemp "${zshrc}.XXXXXX") || exit 1
awk -v n="$starship_line" 'NR == n { print "prompt off" } { print }' \
    "$zshrc" >"$tmp" || { rm -f "$tmp"; exit 1; }

# Preserve whatever mode and ownership the original had.
cp --attributes-only --preserve=all "$zshrc" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$zshrc" || { rm -f "$tmp"; exit 1; }

echo "  inserted 'prompt off' before starship init"
echo "  open a new terminal to see it"
