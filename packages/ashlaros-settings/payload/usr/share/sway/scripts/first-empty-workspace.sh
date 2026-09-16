#!/bin/sh
# Switch to, or move the focused container to, the lowest-numbered empty
# workspace.
#
# Replaces a python3 + i3ipc script. i3ipc was never a declared dependency
# of this package: it arrived through nwg-wrapper and flashfocus, so the
# keybindings would have broken the moment either of those left.
#
# get_tree rather than get_workspaces, because GET_WORKSPACES carries seven
# properties per workspace and none of them says whether anything is open
# on it. The tree is the only reply that does, and it is the same single
# round trip either way.

set -eu

usage() {
	echo "usage: ${0##*/} [-s|--switch] [-m|--move]" >&2
	echo "  at least one of the two is required" >&2
	exit 2
}

switch=false
move=false

[ $# -gt 0 ] || usage
for arg in "$@"; do
	case "$arg" in
	-s | --switch) switch=true ;;
	-m | --move) move=true ;;
	*) usage ;;
	esac
done
[ "$switch" = true ] || [ "$move" = true ] || usage

# The lowest free number in 1..10, where "free" is a number no workspace
# uses plus any workspace that exists and holds nothing. Named workspaces
# report num -1 and are skipped, which is what the python did.
#
# Empty means no tiled *and* no floating children: a workspace holding only
# a floating terminal is occupied, and the python missed that because it
# tested .nodes alone.
#
# Every workspace is tested, not only the focused one. An empty workspace on
# a second output was previously stranded, because the python treated any
# workspace it did not have focus on as occupied.
target=$(swaymsg -t get_tree --raw | jq '
      [ .. | objects | select(.type == "workspace") | select(.num > 0) ] as $ws
    | ( [ $ws[] | .num ] ) as $used
    | ( [ $ws[]
          | select((.nodes | length) == 0 and (.floating_nodes | length) == 0)
          | .num ] ) as $empty
    | ( [ $ws[] | select([.. | objects | select(.focused == true)] | length > 0) ]
        | first ) as $cur
    | ( ([range(1; 11)] - $used) + $empty | unique ) as $free
    | if ($free | length) > 0 then ($free | min) else ($cur.num // 1) end
')

# One command when doing both, so the wallpaper does not flicker between a
# move and the switch that follows it.
if [ "$move" = true ] && [ "$switch" = true ]; then
	command="move container to workspace number $target, workspace number $target"
elif [ "$switch" = true ]; then
	command="workspace number $target"
else
	command="move container to workspace number $target"
fi

# sway reports a failed command in the reply body and still exits 0, so the
# status has to come from the reply.
swaymsg -- "$command" | jq -e 'all(.[]; .success)' >/dev/null
