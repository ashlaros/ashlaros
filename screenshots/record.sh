#!/usr/bin/env bash
#
# Record a short silent tour of the desktop, headless.
#
# A still shows what the desktop looks like; it cannot show the theme
# switching, a launcher opening, or a window being tiled. This is the same
# session.sh the screenshots use, with wf-recorder running across the whole
# sequence instead of grim firing once per scene.
#
# wf-recorder is the desktop's own recorder - it is what Super+Shift+r
# runs - and the encoder settings come from the shipped recorder.sh, so
# this records the desktop with the desktop's own tools.
#
# Silent, deliberately: a container has no audio, and silence means no
# narration to maintain and no localisation question.
set -uo pipefail

out_dir=${1:-/out}
manifest=${SCENES:-/screenshots/scenes.yaml}
video="$out_dir/tour.webm"

# Before sourcing - exec from inside a sourced file would replace this
# script mid-source. See capture.sh for why the bus is needed at all.
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    exec dbus-run-session -- "$0" "$@"
fi

# shellcheck source=screenshots/session.sh
. "$(dirname "$0")/session.sh"

python3 - "$manifest" <<'PY' > /tmp/scenes.jsonl
import json, sys, yaml
for scene in yaml.safe_load(open(sys.argv[1])):
    print(json.dumps(scene))
PY

field() { printf '%s' "$1" | python3 -c "import json,sys; print(json.load(sys.stdin).get('$2', '$3'))"; }
lines() { printf '%s' "$1" | python3 -c "import json,sys; print('\n'.join(json.load(sys.stdin).get('$2', [])))"; }

# libvpx with the parameters recorder.sh already ships, so a published tour
# and a user's own recording are encoded the same way. -f last: wf-recorder
# takes the file as the final argument.
log "recording to $video"
wf-recorder -c libvpx \
    --codec-param="qmin=0" --codec-param="qmax=25" \
    --codec-param="crf=4" --codec-param="b:v=1M" \
    -f "$video" >"$out_dir/recorder.log" 2>&1 &
recorder=$!

# a beat before anything moves, so the first frames are not mid-launch
sleep 2

while read -r scene; do
    name=$(field "$scene" name '')
    step=$(field "$scene" step 2)
    hold=$(field "$scene" hold 3)
    overlay=$(field "$scene" overlay '')
    overlay_settle=$(field "$scene" overlay_settle 2)
    log "=== $name ==="

    while read -r cmd; do
        [ -n "$cmd" ] || continue
        log "  run: $cmd"
        case $cmd in
            # placement between launches, not an app: sway applies a split
            # to the focused container, so it has to run while the previous
            # window is focused and before the next one opens
            swaymsg*) sh -c "$cmd" >/dev/null 2>&1 || true ;;
            *) (cd "$HOME" && setsid sh -c "$cmd" >/dev/null 2>&1 &) ;;
        esac
        sleep "$step"
    done < <(lines "$scene" commands)

    if [ -n "$overlay" ]; then
        log "  overlay: $overlay"
        (cd "$HOME" && setsid sh -c "$overlay" >/dev/null 2>&1 &)
        sleep "$overlay_settle"
    fi

    sleep "$hold"
done < /tmp/scenes.jsonl

# SIGINT, not SIGKILL: wf-recorder finalises the container on interrupt,
# and a killed encoder leaves a file that looks present and does not play.
log "stopping the recorder"
kill -INT "$recorder" 2>/dev/null
wait "$recorder" 2>/dev/null

session_end

# A zero-length or truncated file is worse than none: it publishes over a
# working tour and nobody notices until someone clicks it.
[ -s "$video" ] || { log "no video was produced"; exit 1; }
if command -v ffprobe >/dev/null; then
    duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$video" 2>/dev/null)
    log "duration: ${duration:-unknown}s"
    case ${duration%%.*} in
        '' | 0) log "the video is empty"; exit 1 ;;
    esac
fi

ls -la "$video"
