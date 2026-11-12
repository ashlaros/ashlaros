#!/usr/bin/env bash
#
# Speaker drop-ins written before this carry no guards on the playback
# stream's target. Without them WirePlumber restores a target for that
# stream from its own persisted state, and a stale one naming the
# calibration's own sink is rejected by canLink - with dont-fallback
# set, the linking event then stops instead of falling back, so apps
# play into the filter and no sound reaches the speaker. measure.py
# writes the guards into every drop-in it produces; this puts them
# into the ones already in $HOME, which are only rewritten when the
# user re-measures. Same shape as 1793630019: a file made before the
# change keeps it until this runs.
set -uo pipefail

echo "Guard the calibrated speakers against a stale playback target"

dir="${XDG_CONFIG_HOME:-$HOME/.config}/pipewire/ashlaros-speakers.conf.d"

if ! compgen -G "$dir/*.conf" >/dev/null; then
    echo "  no speaker drop-ins; nothing to patch"
    exit 0
fi

# Exactly what measure.py writes after media.role, so a patched drop-in
# and a freshly measured one differ only in their deviation report.
guards=$(cat <<'EOF'
        # this stream's target is filter.smart.target above and nothing
        # else: a target restored from stream state can name this
        # filter's own sink, canLink rejects it for the shared
        # link-group, and dont-fallback then stops the linking event
        # instead of falling back - the filter never reaches the
        # speaker and every app plays into silence
        state.restore-target = false
        node.dont-move = true
EOF
)

patched=0
for f in "$dir"/*.conf; do
    # written by a measure.py that already guards it
    if grep -q 'state.restore-target' "$f"; then
        echo "  $(basename "$f") already guarded, leaving it alone"
        continue
    fi
    # only a drop-in this shape is patched; anything else is not ours
    # to rearrange
    if ! grep -q '^[[:space:]]*media\.role = "DSP"$' "$f"; then
        echo "  $(basename "$f") has no media.role line; not guessing where the guards belong"
        continue
    fi
    tmp=$(mktemp "${f}.XXXXXX") || exit 1
    GUARDS=$guards awk '
        { print }
        /^[[:space:]]*media\.role = "DSP"$/ && !done {
            print ENVIRON["GUARDS"]
            done = 1
        }
    ' "$f" >"$tmp" || { rm -f "$tmp"; exit 1; }
    chmod --reference="$f" "$tmp" 2>/dev/null || true
    mv -- "$tmp" "$f"
    patched=$((patched + 1))
    echo "  guarded $(basename "$f")"
done

# The service reads the drop-ins when it starts, so the running filter
# still has the old props: reload it here rather than leaving the
# silence until the next login. A reload that fails is retried at the
# next one, when the files are already patched.
if ((patched)) && ! systemctl --user restart ashlaros-speakers.service; then
    echo "  could not reload ashlaros-speakers.service; run: systemctl --user restart ashlaros-speakers.service" >&2
    exit 1
fi
