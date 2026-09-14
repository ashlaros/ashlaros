#!/bin/sh
# Select a region containing a QR code and put its contents on the
# clipboard. The mirror image of wifi-qr.sh, which writes one.
set -u

command -v zbarimg >/dev/null || {
    notify-send "QR" "zbar is not installed."
    exit 1
}

selection=$(slurp 2>/dev/null) || exit 0
[ -n "$selection" ] || exit 0

# QR only. Leaving the other symbologies enabled lets dense screen content
# false-positive as an EAN or Code 39 barcode and take over the clipboard.
value=$(grim -g "$selection" - 2>/dev/null |
    zbarimg -q --raw -Sdisable -Sqrcode.enable - 2>/dev/null)

if [ -z "$value" ]; then
    notify-send "QR" "No QR code in that region."
    exit 0
fi

# QR codes routinely carry secrets - the otpauth:// URIs behind 2FA setup
# codes above all - so the decoded value goes to the clipboard and nowhere
# else. Not printed, not in the notification: either would put it in the
# session journal or the notification history.
#
# --sensitive is load-bearing rather than decoration here, because we ship
# cliphist and wl-clip-persist: an unmarked entry really would be kept.
printf '%s' "$value" | wl-copy --sensitive
notify-send "QR" "QR code copied."
