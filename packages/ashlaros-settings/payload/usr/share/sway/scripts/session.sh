#!/usr/bin/env sh
# The sway session's lifetime, as systemd sees it: sway-session.target is
# up while this sway is, and down before its Wayland socket goes away.
#
# Every session unit is PartOf=sway-session.target (or wayland-session,
# which it binds), but nothing used to start the target - units came up
# through `systemctl --user enable --now` in autostart and were never tied
# to it. So a logout left them running against a dead display: each one
# failed, Restart=on-failure brought it back once a second with nothing to
# connect to, and by the time the next session started them they had hit
# the start limit and stayed down - no polkit agent, no clipboard history,
# no automount, no screen-sharing portal for the rest of that login.
#
# Stopping the target instead stops those units cleanly, which is not a
# failure, so there is no restart loop and the next login starts them.
#
# Run once from sway's config with exec, not exec_always: a reload must not
# stop the session it is reloading.

# sway's environment first, the same way $import_environment hands it
# over. This runs on its own exec beside that one, and sway starts both at
# once, so without it the target could bring units up before they can see
# WAYLAND_DISPLAY - the order is guaranteed here rather than hoped for.
dbus-update-activation-environment --systemd --all

# A crash leaves the previous session's units failed; clear that so the
# start below can bring them up instead of being refused.
systemctl --user reset-failed

systemctl --user start sway-session.target

# `subscribe` returns when sway sends its shutdown event, which it does on
# `swaymsg exit` before tearing down. If sway dies without one, the IPC
# connection closing ends the subscribe just the same.
swaymsg -t subscribe '["shutdown"]' >/dev/null 2>&1

systemctl --user stop sway-session.target wayland-session.target
