#!/bin/sh
# Lock the screen with whatever locker is installed.
#
# swaylock's styling is NOT passed here. It reads
# $XDG_CONFIG_HOME/swaylock/config by default, which
# generate-swaylock-config.sh writes from the active sway theme - so the
# lock screen follows a theme switch, and it does so however it is
# started: this script, swayidle's timeout, or before-sleep.
#
# swaylock-effects is gone: the fork sat at 1.7.0.0 against upstream's
# 1.8.6, which is a long way behind on a screen that stands between a
# locked machine and its session. The branch that probed for its
# --effect-blur went with it.

if [ -x "$(command -v gtklock)" ]; then
	gtklock --daemonize --follow-focus --idle-hide --start-hidden
elif [ -x "$(command -v waylock)" ]; then
	waylock
elif [ -x "$(command -v swaylock)" ]; then
	swaylock
fi
