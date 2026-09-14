#!/usr/bin/env sh

# brightnessctl's -d takes a glob and addresses every device that matches,
# so the loop this used to carry was not only iterating over a $DEVICES
# that is set nowhere - and therefore never running - it was never needed.
case $1'' in
    'on')
        brightnessctl -r -d "*kbd_backlight"
        ;;
    'off')
        brightnessctl -s -d "*kbd_backlight" && brightnessctl -d "*kbd_backlight" set 0
        ;;
esac
