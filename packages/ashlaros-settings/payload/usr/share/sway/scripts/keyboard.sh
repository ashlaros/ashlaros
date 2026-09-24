#!/usr/bin/env sh
# Applies localectl's X11 keymap to every keyboard in the running session:
# the layouts, their variants and the options - the layout switch key is
# one of those (grp:caps_toggle and friends), so a second layout without
# its options would be one nothing can switch to.
status=$(localectl status)
x11() { printf '%s\n' "$status" | sed -n "s/^ *X11 $1: *//p"; }
layout=$(x11 Layout)
[ -n "$layout" ] || exit 0

# One swaymsg, the variants cleared first: sway rebuilds the keymap after
# every command, so no step in between pairs the new layout list with the
# previous one's variants.
k="input type:keyboard"
cmd="$k xkb_variant \"\"; $k xkb_layout \"$layout\"; $k xkb_variant \"$(x11 Variant)\""
# Options are left alone where config.d sets its own - ctrl:nocaps without
# a layout is a reasonable thing to put there, and this would clear it.
if ! grep -qs xkb_options "$HOME"/.config/sway/config.d/*.conf; then
    cmd="$cmd; $k xkb_options \"$(x11 Options)\""
fi
count() {
    swaymsg -t get_inputs --raw |
        jq '[.[] | select(.type == "keyboard") | .xkb_layout_names | length] | max // 0'
}
before=$(count)
swaymsg "$cmd"

# waybar's sway/language decides hide-single-layout once, when it starts,
# and never again: a second layout added to a running session switched
# fine but the module stayed hidden, so nothing showed that it had.
# Restarted only when the number of layouts changed - this also runs on
# every reload, and a bar that blinks on each theme switch is worse.
if [ "$before" != "$(count)" ] && systemctl --user -q is-active waybar; then
    systemctl --user restart waybar
fi
