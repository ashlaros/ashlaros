#!/bin/sh
# Select a region of the screen and ask a model about it.
#
# The opposite of capture-text.sh and capture-qr.sh, which are safe by
# construction because nothing leaves the machine. This sends a picture of
# part of your screen to whichever provider you configured, so every rule
# below is about making that deliberate and visible rather than quiet.
#
# aichat is the frontend precisely so the provider is your choice, not
# ours: it speaks to Ollama and any OpenAI-compatible endpoint as readily
# as to a SaaS, and a local model means this feature costs no privacy at
# all. See the README.
set -u

# Absent rather than broken, the convention autostart uses throughout:
# aichat is an optdepend, so most desktops will not have it.
command -v aichat >/dev/null || {
    notify-send "Ask" "aichat is not installed: pacman -S aichat"
    exit 1
}

# No default provider and no bundled key. Unconfigured, aichat exits 1 on
# a missing config.yaml without touching the network, so this check is
# also what keeps an unconfigured machine from sending anything anywhere.
config="${AICHAT_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/aichat}/config.yaml"
[ -f "$config" ] || {
    notify-send "Ask" "No model configured. Run aichat in a terminal to set a provider - a local Ollama keeps this on the machine."
    exit 1
}

selection=$(slurp 2>/dev/null) || exit 0
# cancelled selection sends nothing
[ -n "$selection" ] || exit 0

# rofi in dmenu mode with no candidates is the shipped way to ask for a
# line of text - $clipboard and inhibit-idle use the same shape.
question=$(printf '' | rofi -dmenu -lines 0 \
    -p "Ask about this region" 2>/dev/null) || exit 0
[ -n "$question" ] || exit 0

shot=$(mktemp -t ashlaros-ask-XXXXXX.png) || exit 1
# the region only - never the full screen
grim -g "$selection" "$shot" 2>/dev/null || { rm -f "$shot"; exit 1; }

# Say what is being sent, at the moment it is sent. A region of screen can
# hold a password manager, a private message, a client's data; "a picture
# of that region just went to a third party" should never be something a
# user finds out afterwards.
provider=$(aichat --info 2>/dev/null | sed -n 's/^model *//p' | head -1)
notify-send "Ask" "Sending that region to ${provider:-your configured model}…"

answer=$(aichat -f "$shot" -- "$question" 2>&1)
status=$?
rm -f "$shot"

if [ $status -ne 0 ]; then
    notify-send "Ask" -- "$(printf '%s' "$answer" | head -c 200)"
    exit 1
fi

# Clipboard, following capture-text.sh, plus the answer in the
# notification: it is prose, and unlike the QR path it is not a secret we
# have to keep out of the notification history.
printf '%s' "$answer" | wl-copy
# -- for the same reason as the error above: this is a remote model's prose
notify-send "Ask" -- "$(printf '%s' "$answer" | head -c 400)"
