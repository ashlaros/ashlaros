#!/usr/bin/env bash
#
# skel's topgrade.toml now disables topgrade's mise step and runs
# `mise plugins update && mise upgrade` as a custom command instead. The
# built-in step runs `mise self-update` first, which both mise builds we
# install refuse, and topgrade then fails the step before `mise upgrade` -
# so the update button left every mise-installed tool where it was.
#
# /etc/skel is copied once, at account creation. A copy that is still the
# only topgrade.toml skel ever shipped (dc1fbc0) is replaced; an edited one
# is left alone, and this says what to add.
set -uo pipefail

echo "Let topgrade update mise's tools without trying to update mise"

config="${XDG_CONFIG_HOME:-$HOME/.config}/topgrade.toml"
skel=/etc/skel/.config/topgrade.toml
unedited=0bc20ddee4a2f643e92ae43d6273f8e8387f1677fe3c9282d41e6bb867db609f

if [ ! -f "$config" ]; then
    echo "  no topgrade.toml; nothing to update"
    exit 0
fi

if grep -q '^"mise tools"' "$config"; then
    echo "  already has the mise tools command"
    exit 0
fi

if [ "$(sha256sum < "$config" | cut -d' ' -f1)" != "$unedited" ]; then
    echo "  $config was edited; leaving it. To get the fix, add"
    echo "    disable = [\"mise\"]   under [misc]"
    echo "  and under [commands]:"
    echo "    \"mise tools\" = \"mise plugins update && mise upgrade\""
    exit 0
fi

[ -f "$skel" ] || { echo "  $skel is missing"; exit 1; }
cp --backup -- "$skel" "$config"
echo "  replaced with the shipped one"
