#!/bin/sh
# The waybar power-profile module, and the click that cycles it.
#
# power-profiles-daemon was installed and enabled with nothing offering it
# (#67). The bar is where a user looks for this, beside the battery.
#
# check:  whether this machine has profiles at all, for exec-if
# status: the JSON waybar renders
# toggle: next profile, wrapping
#
# The daemon is the state. Nothing is cached here, because the profile can
# also be changed from the settings TUI, by a laptop's own hotkey, or
# automatically when a machine overheats - a remembered value would be
# wrong in all three cases.

profiles() {
    # names only: a block's first line, minus the active marker and colon
    powerprofilesctl list 2>/dev/null |
        sed -n 's/^[* ]*\([a-z-]*\):$/\1/p'
}

case ${1:-status} in
'check')
    # A machine the daemon cannot drive lists nothing, and the module
    # should be absent rather than empty. `get` answering is the same
    # predicate the settings entry uses, so the bar and the menu agree.
    powerprofilesctl get >/dev/null 2>&1
    exit $?
    ;;
'toggle')
    current=$(powerprofilesctl get 2>/dev/null) || exit 1
    # the list is short and ordered power-saver..performance; wrapping
    # past the end returns to the first, so one binding reaches them all
    next=$(profiles | awk -v cur="$current" '
        { p[NR] = $0 }
        END {
            for (i = 1; i <= NR; i++)
                if (p[i] == cur) { print p[i % NR + 1]; exit }
            print p[1]
        }')
    [ -n "$next" ] || exit 1
    powerprofilesctl set "$next" || exit 1
    waybar-signal power >/dev/null 2>&1 || true
    ;;
'status' | *)
    current=$(powerprofilesctl get 2>/dev/null) || exit 1

    # A degraded profile is the difference between "performance is off"
    # and "performance is on and doing nothing", which is worth a tooltip
    # rather than a silent lie.
    degraded=$(powerprofilesctl list 2>/dev/null |
        awk -v cur="$current" '
            /^[* ]*[a-z-]*:$/ { name = $0; gsub(/[* :]/, "", name) }
            name == cur && /Degraded:/ {
                sub(/.*Degraded:[ \t]*/, "")
                if ($0 != "no") { print; exit }
            }')

    # Labelled, not bare. The bar shows an icon and nothing else, so the
    # tooltip is the only place the profile is named - and a lone
    # "balanced" reads as a stray word rather than as the power mode.
    # The click action goes with it: cycling is not discoverable from an
    # icon, and the tooltip is where waybar can say so.
    tooltip="Power mode: $current"
    if [ -n "$degraded" ]; then
        tooltip="$tooltip
Degraded: $degraded"
    fi
    tooltip="$tooltip
Click to cycle, right-click for settings"

    # jq, not printf: the tooltip carries real newlines now, and a raw
    # newline inside a JSON string is invalid - waybar drops the module
    # rather than complaining. --arg escapes them.
    jq -cn --arg alt "$current" --arg tooltip "$tooltip" --arg class "$current" \
        '{alt: $alt, tooltip: $tooltip, class: $class}'
    ;;
esac
