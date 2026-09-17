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
failed=" "

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
    theme=$(field "$shot" theme '')
    log "=== $name ==="

    # A shot can ask for a theme, which is how the variants get one picture
    # each (#84). The same copy-and-reload ashlaros-theme does, without its
    # rofi prompts: sway rereads definitions.d/theme.conf on reload, so no
    # session restart is needed.
    if [ -n "$theme" ]; then
        theme_dir="/usr/share/sway/themes/$theme"
        if [ -f "$theme_dir/theme.conf" ]; then
            log "  theme: $theme"
            cp "$theme_dir/theme.conf" "$HOME/.config/sway/definitions.d/theme.conf"
            [ -f "$theme_dir/foot-theme.ini" ] &&
                cp "$theme_dir/foot-theme.ini" "$HOME/.config/foot/foot-theme.dark.ini_"
            /usr/share/sway/scripts/theme-toggle.sh merge-foot 2>/dev/null || true
            swaymsg reload >/dev/null 2>&1 || true
            # the reload restarts the bar and the wallpaper, which the shot
            # would otherwise photograph mid-flight
            sleep 4
        else
            log "  theme: $theme has no theme.conf, skipping the shot"
            continue
        fi
    fi

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

    # A shot that asked for windows must have them. `settings` published a
    # picture of bare wallpaper because the TUI exited before grim fired -
    # ashlaros-settings did not depend on gum - and nothing here could
    # tell an empty desktop from a desktop that was meant to be empty.
    #
    # Counted from sway rather than from the pixels: a window that opened
    # and closed leaves no trace in the image, and "is anything running"
    # is the question, not "is the picture dark".
    # `layer: true` marks a shot whose subject is a layer surface - the
    # help overlay is eww's, not an app_id window - so the count below
    # would fail it for having launched nothing, when what it launched is
    # exactly what is meant to be on screen.
    if [ -n "$(lines "$shot" commands)" ] && [ "$(field "$shot" layer false)" != "True" ]; then
        windows=$(swaymsg -t get_tree |
            python3 -c 'import json,sys
def walk(n):
    return (1 if n.get("app_id") else 0) + sum(walk(c) for c in n.get("nodes", []) + n.get("floating_nodes", []))
print(walk(json.load(sys.stdin)))')
        if [ "$windows" -eq 0 ]; then
            log "  ERROR: $name launched apps and has no windows"
            failed="$failed $name"
            continue
        fi
    fi

    # A shot may state what has to be true of what it photographed. The
    # window count above only asks whether something is on screen; an
    # overlay can be on screen and rendering nonsense, which is how a
    # broken help overlay was published twice by a green job.
    #
    # Run before grim rather than after: a shot that fails still writes its
    # picture, and the picture is the evidence for the failure.
    assert_failed=""
    while read -r check; do
        [ -n "$check" ] || continue
        if ! (cd "$HOME" && sh -c "$check") >/dev/null 2>&1; then
            log "  ERROR: $name failed its check: $check"
            assert_failed=yes
        fi
    done < <(lines "$shot" assert)

    grim "$out_dir/$name.png"
    log "  wrote $name.png ($(stat -c%s "$out_dir/$name.png") bytes)"

    if [ -n "$assert_failed" ]; then
        failed="$failed $name"
    fi

    # Anything the shot has to undo. The per-shot cleanup kills app_id
    # windows only, so a shot that opened a layer surface has to close it
    # or it sits over every picture taken after this one.
    while read -r cmd; do
        [ -n "$cmd" ] || continue
        log "  after: $cmd"
        sh -c "$cmd" >/dev/null 2>&1 || true
    done < <(lines "$shot" after)
done < /tmp/shots.jsonl

session_end

if [ -n "${failed# }" ]; then
    echo "shots that failed:$failed" >&2
    exit 1
fi

ls -la "$out_dir"/*.png
