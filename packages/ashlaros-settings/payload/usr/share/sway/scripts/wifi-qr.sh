#!/bin/bash
# Show the current Wi-Fi as a QR code, so a guest can join by pointing a
# phone at the screen instead of typing a passphrase off a sticky note.
#
# This renders a live credential. It is an explicit action, never
# something the bar shows on its own, and the secret is never written
# anywhere - not to a file, not to a log, and not to a command line.
set -uo pipefail

die() {
    echo "$*" >&2
    exit 1
}

# nmcli localises state names, so a locale where "connected" is spelled
# differently silently matches nothing. Prefix matching keeps states like
# `connected (externally)` parsing.
export LC_ALL=C

command -v nmcli >/dev/null || die "NetworkManager is not installed."
command -v qrencode >/dev/null || die "qrencode is not installed."

# The default-route device first - on a machine with several wifi cards
# that is the one actually carrying traffic - then any connected wifi.
device=$(ip route show default 2>/dev/null | awk '/^default/ {print $5; exit}')
if [[ -z ${device:-} ]] ||
    ! nmcli -t -f DEVICE,TYPE device 2>/dev/null | grep -q "^$device:wifi$"; then
    device=$(nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null |
        awk -F: '$2 == "wifi" && $3 ~ /^connected/ {print $1; exit}')
fi
[[ -n ${device:-} ]] || die "No connected Wi-Fi device."

profile=$(nmcli -t -f NAME,DEVICE connection show --active 2>/dev/null |
    awk -F: -v d="$device" '$2 == d {print $1; exit}')
[[ -n ${profile:-} ]] || die "No active connection on $device."

# --show-secrets needs root or a polkit prompt. Asking is the honest
# failure: a QR button that silently renders a passwordless network is
# worse than one that says what it needs.
settings=$(nmcli --show-secrets -t -f 802-11-wireless,802-11-wireless-security \
    connection show "$profile" 2>/dev/null) ||
    die "Could not read the connection. Reading the passphrase needs authorisation."

field() {
    printf '%s\n' "$settings" | awk -F: -v k="$1" '$1 == k {sub(/^[^:]*:/, ""); print; exit}'
}

ssid=$(field 802-11-wireless.ssid)
hidden=$(field 802-11-wireless.hidden)
keymgmt=$(field 802-11-wireless-security.key-mgmt)
psk=$(field 802-11-wireless-security.psk)
wep=$(field 802-11-wireless-security.wep-key0)

[[ -n ${ssid:-} ]] || die "Could not read the network name."

# An enterprise network has no shareable secret - the credential is a
# per-user identity, not a passphrase - so emitting a QR code for one
# would produce something that cannot work.
case $keymgmt in
*eap* | *ieee8021x*)
    die "$ssid is an enterprise network: there is no passphrase to share."
    ;;
esac

# WEP is modelled as key-mgmt "none" with the key in wep-key0, so a
# script that only looks at psk reports an open network and produces a
# QR code that fails to join.
if [[ -n ${psk:-} ]]; then
    auth=WPA
    secret=$psk
elif [[ -n ${wep:-} ]]; then
    auth=WEP
    secret=$wep
else
    auth=nopass
    secret=""
fi

# `\`, `;`, `,` and `:` are significant in the WIFI: payload. A passphrase
# containing a semicolon otherwise ends the field early and the code scans
# to the wrong thing - silently, because it still scans.
escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/;/\\;/g' -e 's/,/\\,/g' -e 's/:/\\:/g'
}

payload="WIFI:S:$(escape "$ssid");T:$auth;P:$(escape "$secret");"
[[ $hidden == yes ]] && payload+="H:true;"
payload+=";"

printf '\n  %s' "$ssid"
[[ $auth == nopass ]] && printf '  (open network)'
printf '\n\n'
# The payload goes in on stdin, which is a private pipe: as an argument it
# would be the passphrase, visible in /proc to every process on the
# machine for as long as qrencode runs.
printf '%s' "$payload" | qrencode -t ANSIUTF8 -o -
printf '\n  Scan to join. Press any key to close.\n'
read -r -n 1 -s
