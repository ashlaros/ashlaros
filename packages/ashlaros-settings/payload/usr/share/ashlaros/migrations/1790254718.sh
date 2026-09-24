#!/usr/bin/env bash
#
# skel's sworkstyle config now prefers nf-dev icons where Nerd Fonts has
# one for the application: dev-terminal (U+E795) for footclient and
# floating_shell, dev-slack (U+E8A4) for slack, dev-vscode (U+E8DA) for
# com.microsoft.VSCode. Earlier migrations wrote the nf-fa ones -
# fa-terminal (U+F120), fa-slack (U+F198), fa-code (U+F121).
#
# Only a line that still carries exactly the fa icon we wrote is changed;
# an entry the user changed to anything else is theirs and stays.
set -uo pipefail

echo "Use nf-dev icons for the terminal, Slack and VS Code in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

# app_id, the fa icon we shipped, the dev icon replacing it - both as UTF-8
# bytes, so this file stays ASCII
swap() {
    local app=$1 old=$2 new=$3 from to
    from="'$app' = '$old'"
    to="'$app' = '$new'"
    grep -qxF "$from" "$config" || return 0
    sed -i "s|^${from//./\\.}\$|$to|" "$config" || return 1
    echo "  $app: nf-fa icon replaced with nf-dev"
}

swap footclient $'\xef\x84\xa0' $'\xee\x9e\x95' || exit 1
swap floating_shell $'\xef\x84\xa0' $'\xee\x9e\x95' || exit 1
swap slack $'\xef\x86\x98' $'\xee\xa2\xa4' || exit 1
swap com.microsoft.VSCode $'\xef\x84\xa1' $'\xee\xa3\x9a' || exit 1
