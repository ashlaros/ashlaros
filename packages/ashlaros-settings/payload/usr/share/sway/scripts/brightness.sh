#!/bin/sh
# Brightness for the key bindings and the waybar module.
#
# Two mechanisms, because they address different hardware and neither
# covers the other. brightnessctl writes /sys/class/backlight, which is a
# laptop panel and nothing else - a desktop has no such device, so every
# brightness control here used to run against nothing and report nothing.
# An external monitor is reached over DDC/CI on its i2c line, which is
# ddcutil's setvcp 10.
#
# The panel wins when there is one: a laptop with a monitor plugged in
# should still have its own keys dim its own screen, and DDC is slow
# enough (a round trip per monitor, tens of ms at best) that it is worth
# avoiding when there is nothing to use it for.

factor=3

has_panel() {
    # `brightnessctl get` prints 0 and exits 0 with no device at all, so
    # the device list is what decides, not a reading.
    [ -n "$(ls -A /sys/class/backlight 2>/dev/null)" ]
}

panel_rel() {
    max=$(brightnessctl max)
    [ "$max" -gt 0 ] 2>/dev/null || return 1
    echo "$(brightnessctl get) * 100 / $max" | bc
}

panel() {
    max=$(brightnessctl max)
    step=$((max * factor / 100 < 1 ? 1 : max * factor / 100))
    case $1 in
    down)
        # at or below one step, go to 1 rather than 0: a screen that has
        # been dimmed to black cannot be found again by looking at it
        if [ "$(panel_rel)" -le "$factor" ]; then
            brightnessctl --quiet set 1
        else
            brightnessctl --quiet set "${step}-"
        fi
        ;;
    up) brightnessctl --quiet set "${step}+" ;;
    esac
    panel_rel
}

ddc() {
    # VCP feature 10 is the standard brightness control. Every detected
    # display gets the same change, which is what a brightness key on a
    # multi-monitor desktop is asking for.
    #
    # `ddcutil --brief getvcp 10` prints: VCP 10 C <current> <max>
    displays=$(ddcutil --brief detect 2>/dev/null | sed -n 's/^Display \([0-9]*\)/\1/p')
    [ -n "$displays" ] || return 1

    for d in $displays; do
        case $1 in
        down) ddcutil --brief --display "$d" setvcp 10 - $factor >/dev/null 2>&1 ;;
        up) ddcutil --brief --display "$d" setvcp 10 + $factor >/dev/null 2>&1 ;;
        esac
    done

    # the first display's value, for the bar: one number is what the
    # overlay shows, and the displays were all moved by the same step
    first=$(echo "$displays" | head -1)
    ddcutil --brief --display "$first" getvcp 10 2>/dev/null |
        awk '/^VCP 10/ {if ($5 > 0) printf "%d\n", $4 * 100 / $5}'
}

if has_panel; then
    panel "$1"
elif command -v ddcutil >/dev/null 2>&1; then
    ddc "$1"
fi
