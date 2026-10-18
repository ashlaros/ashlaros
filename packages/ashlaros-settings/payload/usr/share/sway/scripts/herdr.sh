#!/usr/bin/env bash
# The waybar herdr module: agents that need you, across the local herdr
# server and every saved machine (`herdr machine add`).
#
#   blocked  herdr recognised an approval prompt or a question   ●N
#   done     finished, and nobody has looked at it yet            ✓N
#
# check:  whether herdr is installed, for exec-if
# status: the JSON waybar renders; empty when nothing needs you
# focus:  focus the first blocked agent (else the first done one) on its
#         server, which also marks it seen, and raise a herdr window
#
# Remote machines are read through `herdr --machine <id> api snapshot`,
# herdr's own forwarding: the SSH target, session and remote binary are
# whatever `herdr machine add` saved, the connection is non-interactive
# (BatchMode, 10 s connect timeout) and reused between calls, so a poll
# costs a fraction of a second and can never stop at a password prompt.
# A machine that does not answer is named in the tooltip rather than
# hiding the others.
#
# herdr's event subscription would push changes instead of polling, but
# it is per pane and per server: it misses panes created later, and would
# hold one stream open per machine.

machines() {
    herdr machine list --json 2>/dev/null |
        jq -r '.[] | select(.enabled) | "\(.id)\t\(.label)"'
}

# One server's agents as {server, machine, s, w, t, pane}; nothing when
# it is unreachable or not running. machine is the --machine argument, ""
# for the local server.
agents() {
    local machine=$1 label=$2 snapshot
    if [ -n "$machine" ]; then
        snapshot=$(herdr --machine "$machine" api snapshot </dev/null 2>/dev/null)
    else
        snapshot=$(herdr api snapshot </dev/null 2>/dev/null)
    fi
    jq -ce --arg machine "$machine" --arg label "$label" '
        .result.snapshot
        | (.workspaces | map({(.workspace_id): .label}) | add // {}) as $ws
        | [.agents[] | select(.agent_status == "blocked" or .agent_status == "done")
           | {server: $label, machine: $machine, s: .agent_status,
              w: ($ws[.workspace_id] // .workspace_id),
              t: (.terminal_title_stripped // ""), pane: .pane_id}]
    ' <<<"$snapshot"
}

# Every server's agents as one array, plus the labels of saved machines
# that did not answer. A local server that is not running is not an error:
# most of the time nothing runs here when work is remote.
collect() {
    local id label list unreachable=()
    list=$(agents "" "local") || list='[]'
    while IFS=$'\t' read -r id label; do
        [ -n "$id" ] || continue
        if found=$(agents "$id" "$label"); then
            list=$(jq -c --argjson more "$found" '. + $more' <<<"$list")
        else
            unreachable+=("$label")
        fi
    done < <(machines)
    jq -c --args '{agents: ., unreachable: $ARGS.positional}' "${unreachable[@]}" <<<"$list"
}

status() {
    collect | jq -c '
        def esc: gsub("&"; "&amp;") | gsub("<"; "&lt;") | gsub(">"; "&gt;");
        (.agents | map(select(.s == "blocked")) | length) as $b
        | (.agents | map(select(.s == "done")) | length) as $d
        # name the server on each line unless everything is local
        | (.agents | map(.server) | unique | . != [] and . != ["local"]) as $named
        | if $b + $d == 0 and (.unreachable | length) == 0 then {text: ""}
          else {
            text: ([if $b > 0 then "●\($b)" else empty end,
                    if $d > 0 then "✓\($d)" else empty end,
                    if (.unreachable | length) > 0 then "?" else empty end] | join(" ")),
            class: (if $b > 0 then "blocked" elif $d > 0 then "done" else "unreachable" end),
            tooltip: (
                (.agents | sort_by(.s != "blocked") | map(
                    (if .s == "blocked" then "●" else "✓" end) + " "
                    + (if $named then "\(.server) · " else "" end)
                    + "\(.w): \(.t)"))
                + (.unreachable | map("? \(.) did not answer"))
                + ["",
                   "●N  blocked: waiting for your approval or answer",
                   "✓N  done: finished, not looked at yet",
                   "?   a saved machine did not answer",
                   "hidden while every agent is idle or working",
                   "click: jump to the first blocked (else done) agent"]
                | join("\n") | esc)
          } end'
}

focus() {
    local target
    target=$(collect | jq -r '
        .agents | (map(select(.s == "blocked")) + map(select(.s == "done"))) | .[0]
        | select(.) | "\(.machine)\t\(.pane)"')
    [ -n "$target" ] || exit 0
    local machine=${target%%$'\t'*} pane=${target#*$'\t'}
    if [ -n "$machine" ]; then
        herdr --machine "$machine" agent focus "$pane" >/dev/null
    else
        herdr agent focus "$pane" >/dev/null
    fi
    # skel's .zshrc gives a foot window running herdr this app_id; one
    # client shows every saved machine, so any herdr window will do
    swaymsg -q '[app_id="^terminal-multiplexer$"] focus'
}

case $1 in
    check) command -v herdr >/dev/null ;;
    status) status ;;
    focus) focus ;;
    *)
        echo "usage: $0 check|status|focus" >&2
        exit 2
        ;;
esac
