#!/bin/sh
# Lock the screen with whatever locker is installed.
#
# swaylock's styling is NOT passed here. It reads
# $XDG_CONFIG_HOME/swaylock/config by default, which
# generate-swaylock-config.sh writes from the active sway theme - so the
# lock screen follows a theme switch, and it does so however it is
# started: this script, swayidle's timeout, or before-sleep.
#
# The effects build takes the same config and adds blur on top, so the
# branch below is about capability, not colour.

if [ -x "$(command -v gtklock)" ]; then
	gtklock --daemonize --follow-focus --idle-hide --start-hidden
elif [ -x "$(command -v waylock)" ]; then
	waylock
elif swaylock -h 2>&1 | grep -q "effect-blur"; then
	swaylock --screenshots --clock --effect-blur 7x5 --effect-vignette 0.5:0.5 --fade-in 0.2
elif [ -x "$(command -v swaylock)" ]; then
	swaylock
fi
