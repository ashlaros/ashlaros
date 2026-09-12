#!/usr/bin/env bash
#
# Bring up a headless AshlarOS desktop, for something else to record or
# photograph.
#
# Sourced by capture.sh and record.sh rather than copied into both: this is
# the hard-won part - the D-Bus re-exec, the two pieces systemd --user
# would normally start, the waybar module that segfaults without a
# bluetooth stack - and two copies of that reasoning would drift the first
# time one was touched.
#
# The live ISO is deliberately not the desktop - iso/packages.x86_64
# installs sway, foot and firefox and leaves ashlaros-settings out, because
# the live system is the installer plus a rescue shell. So a shot of a
# booted ISO is bare sway: no bar, no theme, no wallpaper. Callers install
# the settings package from our own repository and render that.
#
# wlroots' headless backend draws a full session with no GPU, no seat and
# no display, which is what makes this a container job of seconds rather
# than a nested-virtualisation job of minutes.
#
# The container needs --cap-add=SYS_NICE: Arch's sway carries
# cap_sys_nice=ep, and exec'ing a file whose capability is outside the
# bounding set fails with EPERM - as root too, which makes it read like a
# corrupt binary rather than a missing capability. Any scene that adds a
# binary with file capabilities (btop wants DAC_READ_SEARCH and PERFMON)
# needs the matching cap-add.
#
# The caller must have re-execed under dbus-run-session before sourcing
# this - see session_needs_dbus below, which cannot do it itself because
# exec from a sourced file would replace the caller mid-source.
set -uo pipefail

out_dir=${out_dir:?the caller sets out_dir before sourcing}
: "${WIDTH:=1920}"
: "${HEIGHT:=1080}"

mkdir -p "$out_dir"

# setup.sh creates this as root: there is no logind in a container, and the
# user cannot make its own directory under /run/user
XDG_RUNTIME_DIR=/run/user/$(id -u)
export XDG_RUNTIME_DIR
[ -d "$XDG_RUNTIME_DIR" ] || { echo "no $XDG_RUNTIME_DIR - run setup.sh first" >&2; exit 1; }

export WLR_BACKENDS=headless
# no GPU in a container, so software rendering; pixman is wlroots' own
export WLR_RENDERER=pixman
export WLR_HEADLESS_OUTPUTS=1
export XDG_CURRENT_DESKTOP=sway
export XDG_SESSION_TYPE=wayland
export XDG_CONFIG_HOME="$HOME/.config"

log() { printf '%s\n' "$*" >&2; }

# The keybinding cheatsheet is shown on a first login and covers half the
# screen. It is a real part of the desktop, and Super+? brings it back, but
# it is not what a screenshot should advertise - it is the thing a new user
# dismisses. Set via the lockfile help.sh reads rather than by killing
# nwg-wrapper, so this uses the desktop's own off switch.
mkdir -p "$HOME/.local"
touch "$HOME/.local/help_disabled"

# sway's config runs `systemctl --user` for most autostarts and there is no
# user manager here, so those lines fail harmlessly and the visible pieces -
# bar, wallpaper, terminal server - are started below instead. Running the
# shipped config unmodified is the point: this must photograph what users
# get, not a mock of it.
sway >"$out_dir/sway.log" 2>&1 &
sway_pid=$!

for _ in $(seq 40); do
    [ -n "${SWAYSOCK:-}" ] || SWAYSOCK=$(find /run/user -name 'sway-ipc.*' -type s 2>/dev/null | head -1)
    [ -n "$SWAYSOCK" ] && break
    sleep 0.25
done
[ -n "${SWAYSOCK:-}" ] || { log "sway never created its socket"; cat "$out_dir/sway.log" >&2; exit 1; }
export SWAYSOCK

# sway's own exec children inherit this; the ones started below are not its
# children, and without it every wayland client exits "failed to create
# display" while sway itself looks perfectly healthy
WAYLAND_DISPLAY=$(basename "$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -name 'wayland-*' -type s | head -1)")
export WAYLAND_DISPLAY
log "sway is on $WAYLAND_DISPLAY"


# the headless output comes up at 1280x720; the shot wants a real resolution
swaymsg "output * mode ${WIDTH}x${HEIGHT}@60Hz" >/dev/null
swaymsg "output * scale 1" >/dev/null

# The two pieces the session would normally get from systemd --user, which
# has no manager here. Everything else the config does - the wallpaper, the
# waybar colours, the theme - runs from sway's own exec_always and is left
# alone: a second copy here would be a mock of the desktop rather than it.
foot --server >"$out_dir/foot.log" 2>&1 &

# waybar's bluetooth module segfaults the whole bar when there is no
# bluetooth stack, which a container has no way to provide. Dropping the
# module here rather than from the shipped config: on real hardware it
# works, and the alternative is photographing no bar at all.
#
# The wrapper is what runs it - it seeds ~/.config/waybar and prefers the
# user config, which is what a real session shows - so the pruned config
# goes where the wrapper already looks.
python3 - <<'EOF'
import json, os, re
src = '/usr/share/sway/templates/waybar/config.jsonc'
raw = re.sub(r'^\s*//.*$', '', open(src).read(), flags=re.M)
config = json.loads(raw)
bars = config if isinstance(config, list) else [config]
for bar in bars:
    for side in ('modules-left', 'modules-center', 'modules-right'):
        if side in bar:
            bar[side] = [m for m in bar[side] if m != 'bluetooth']
    bar.pop('bluetooth', None)
target = os.path.expanduser('~/.config/waybar')
os.makedirs(target, exist_ok=True)
with open(f'{target}/config.jsonc', 'w') as f:
    json.dump(config, f, indent=2)
EOF

/usr/share/sway/scripts/waybar.sh >"$out_dir/waybar.log" 2>&1 &

sleep "${WARMUP:-6}"

# swaybg logs "Found config * for output HEADLESS-1 ((null))" without this:
# the config generates the wallpaper and applies it from two different
# exec blocks, so on a first login the apply can win the race against the
# file existing. Re-issuing the config's own command once the file is there
# is the same command, not a substitute for it.
background="$XDG_CONFIG_HOME/sway/generated_background.svg"
if [ -f "$background" ]; then
    swaymsg "output * bg $background fill" >/dev/null
else
    log "no generated background at $background"
fi

# Teardown, here rather than in each caller: a session left running holds
# the output and the next run in the same container gets a second sway.
session_end() {
    swaymsg exit >/dev/null 2>&1 || kill "$sway_pid" 2>/dev/null || true
    wait "$sway_pid" 2>/dev/null || true
}
