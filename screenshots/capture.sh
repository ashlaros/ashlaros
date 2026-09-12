#!/usr/bin/env bash
#
# Photograph the AshlarOS desktop, headless.
#
# What this is not: proof that anything boots or installs. It is a picture
# of the desktop. The ISO build has its own checks for the other question.
#
# The session itself - the environment, the D-Bus bus, waybar, the
# wallpaper - is session.sh, shared with record.sh.
set -uo pipefail

out_dir=${1:-/out}
manifest=${MANIFEST:-/screenshots/shots.yaml}

# Before sourcing, because exec from inside a sourced file would replace
# this script mid-source. waybar's tray, mako and the portal are D-Bus
# clients: without a session bus waybar exits with "Cannot autolaunch
# D-Bus without X11 $DISPLAY" and the desktop photographs as bare sway.
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    exec dbus-run-session -- "$0" "$@"
fi

# shellcheck source=screenshots/session.sh
. "$(dirname "$0")/session.sh"

# one json object per line: `read` splitting on tabs slides the trailing
# columns left as soon as a field is empty, which silently fed an overlay's
# settle time into the overlay command
python3 - "$manifest" <<'PY' > /tmp/shots.jsonl
import json, sys, yaml
for shot in yaml.safe_load(open(sys.argv[1])):
    print(json.dumps(shot))
PY

field() { printf '%s' "$1" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$2', '$3'))"; }
lines() { printf '%s' "$1" | python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin).get('$2', [])))"; }

while read -r shot; do
    name=$(field "$shot" name '')
    settle=$(field "$shot" settle 3)
    overlay=$(field "$shot" overlay '')
    overlay_settle=$(field "$shot" overlay_settle 2)
    log "=== $name ==="

    # every shot starts from an empty workspace, so one shot's windows can
    # never leak into the next. Matched on app_id rather than workspace:
    # `[workspace=…] kill` also matches swaybg's layer surface, and killing
    # the wallpaper left every shot after the first on bare colour.
    swaymsg '[app_id=".*"] kill' >/dev/null 2>&1 || true
    sleep 1

    while read -r cmd; do
        [ -n "$cmd" ] || continue
        log "  run: $cmd"
        case $cmd in
            # placement between launches, not an app: sway applies a split
            # to the focused container, so it has to run while the previous
            # window is focused and before the next one opens. Detaching it
            # like an app would race the window it is meant to position.
            swaymsg*) sh -c "$cmd" >/dev/null 2>&1 || true ;;
            # from $HOME, not wherever the job checked out: a shell
            # prompt showing /ws or /__w advertises the build machine
            *) (cd "$HOME" && setsid sh -c "$cmd" >/dev/null 2>&1 &) ;;
        esac
        sleep "${STEP:-2}"
    done < <(lines "$shot" commands)

    sleep "$settle"

    while read -r msg; do
        [ -n "$msg" ] || continue
        swaymsg "$msg" >/dev/null 2>&1 || true
    done < <(lines "$shot" layout)

    if [ -n "$overlay" ]; then
        log "  overlay: $overlay"
        # rofi grabs the keyboard and does not return, so it is detached and
        # the capture happens with it on screen
        setsid sh -c "$overlay" >/dev/null 2>&1 &
        sleep "$overlay_settle"
    fi

    grim "$out_dir/$name.png"
    log "  wrote $name.png ($(stat -c%s "$out_dir/$name.png") bytes)"
done < /tmp/shots.jsonl

session_end

ls -la "$out_dir"/*.png
