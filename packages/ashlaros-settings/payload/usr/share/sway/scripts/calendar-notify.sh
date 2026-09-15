#!/usr/bin/env bash
# Appointment reminders, which khal does not do on its own.
#
# calcurse had a notification daemon and khal has nothing equivalent - it
# is a viewer over files, not a resident process. Dropping the reminders
# with the switch would be a silent regression, so this replaces them: a
# timer asks khal what is coming up and notify-send says so.
#
# One notification per event, not one per run: the state file records what
# has already been announced, so a ten-minute timer does not produce the
# same reminder five times.
set -uo pipefail

# How far ahead to look. Matches calcurse's notification.warning = 300,
# which is what this replaces, rounded to the timer's own granularity.
LOOKAHEAD_MINUTES="${CALENDAR_NOTIFY_LOOKAHEAD:-15}"

STATE="${XDG_RUNTIME_DIR:-/tmp}/calendar-notify.seen"

command -v khal >/dev/null || exit 0
command -v notify-send >/dev/null || exit 0

# khal prints nothing and exits 0 when there is no calendar at all, so an
# unconfigured machine costs one process every timer tick and says nothing.
until=$(date -d "+${LOOKAHEAD_MINUTES} minutes" "+%Y-%m-%d %H:%M")

# One line per event, machine-readable: the format string is ours, so the
# parse below does not depend on khal's human output shape.
events=$(khal list --format '{start-time}|{title}|{uid}' \
  --day-format '' now "$until" 2>/dev/null) || exit 0

[[ -n $events ]] || exit 0

touch "$STATE" 2>/dev/null || exit 0

while IFS='|' read -r start title uid; do
  [[ -n $uid ]] || continue
  # An event's reminder fires once. The uid alone is not enough: a
  # recurring event repeats it, so the occurrence's start time is part of
  # the key.
  key="$uid@$start"
  grep -qxF "$key" "$STATE" && continue
  notify-send --app-name=calendar --icon=x-office-calendar \
    "${start:-Soon}" "$title"
  printf '%s\n' "$key" >> "$STATE"
done <<<"$events"

# Keep the state file from growing without bound across a long uptime.
# Reminders older than a day cannot fire again: the lookahead is minutes.
if [[ $(wc -l < "$STATE") -gt 500 ]]; then
  tail -100 "$STATE" > "$STATE.new" && mv "$STATE.new" "$STATE"
fi
