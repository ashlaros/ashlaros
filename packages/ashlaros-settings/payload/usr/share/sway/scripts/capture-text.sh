#!/bin/sh
# Select a region of the screen and put its text on the clipboard.
#
# The useful half of Circle to Search, and entirely local: tesseract runs
# here, nothing leaves the machine. A handoff to a search engine or a
# model is a different privacy story and deliberately not this script.
set -u

command -v tesseract >/dev/null || {
    notify-send "OCR" "tesseract is not installed."
    exit 1
}

# No freeze. omarchy holds a still frame with `hyprpicker -r -z`, which is
# Hyprland-only; the wlroots equivalent (wayfreeze) is a one-vote AUR
# package and not worth a dependency for this. So the screen stays live
# during selection, and the cost is honest: a video or a notification
# appearing between the drag and the capture is what gets captured. For
# the static text this exists to grab, it does not come up.
selection=$(slurp 2>/dev/null) || exit 0
[ -n "$selection" ] || exit 0

# --psm 6 and preserve_interword_spaces are tuned for screen text rather
# than scanned pages; tesseract's defaults are noticeably worse on UI
# screenshots. --dpi 300 silences its DPI guessing on a capture that
# carries no DPI metadata of its own.
#
# ASHLAROS_OCR_LANGS because language data is per-package: a German user
# installs tesseract-data-deu and sets this, without editing the script.
text=$(grim -g "$selection" - 2>/dev/null |
    tesseract stdin stdout \
        --oem 1 --psm 6 \
        -l "${ASHLAROS_OCR_LANGS:-eng}" \
        --dpi 300 \
        -c preserve_interword_spaces=1 2>/dev/null)

if [ -z "$text" ]; then
    notify-send "OCR" "No text found in that region."
    exit 0
fi

printf '%s' "$text" | wl-copy
# The first line, truncated: enough to confirm it grabbed the right thing
# without putting a paragraph in a notification.
# -- because the body is OCR'd from whatever was on screen: text starting
# with a dash is parsed as a flag and the notification is lost, and mako
# renders pango markup in a body, which is why waybar's own config pipes
# media metadata through markup_escape.
notify-send "OCR" -- "Copied: $(printf '%s' "$text" | head -c 60 | tr '\n' ' ')…"
