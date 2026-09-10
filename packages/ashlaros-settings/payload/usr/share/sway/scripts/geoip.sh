#!/bin/sh
# Approximate location and today's sun times, cached for the day.
#
# manjaro-sway proxied this through a cloudflare worker that read the
# request's own geo-ip data and computed sunrise/sunset. We run no such
# worker, so the location comes from geojs.io (no key, no account, no rate
# limit - ipapi.co answers 429 to an unauthenticated caller) and the sun
# times from open-meteo, already the source the weather module uses.
# Consumers - sunset.sh and theme-toggle.sh - read .latitude/.longitude/
# .city/.sunrise/.sunset/.sunrise_tomorrow/.sunset_tomorrow, so this emits
# exactly those keys.
set -u

cache_file="$HOME/.cache/geoip"
cache_time=$(date -r "$cache_file" +%s 2>/dev/null || echo 0)
six_hours_ago=$(date -d 'now - 6 hour' +%s)
start_of_day=$(date -d '00:00' +%s)

if [ ! -f "$cache_file" ] || [ "$cache_time" -lt "$six_hours_ago" ] || [ "$cache_time" -lt "$start_of_day" ]; then
	mkdir -p "$(dirname "$cache_file")"
	tmp_file=$(mktemp "${cache_file}.tmp.XXXXXX") || exit 1

	location=$(curl -fsSL --max-time 10 "https://get.geojs.io/v1/ip/geo.json" 2>/dev/null)
	# geojs sends the coordinates as strings; tonumber here so consumers
	# get the numbers the worker used to return
	latitude=$(echo "$location" | jq -r '.latitude // empty')
	longitude=$(echo "$location" | jq -r '.longitude // empty')

	if [ -n "$latitude" ] && [ -n "$longitude" ]; then
		sun=$(curl -fsSL --max-time 10 \
			"https://api.open-meteo.com/v1/forecast?latitude=${latitude}&longitude=${longitude}&daily=sunrise,sunset&forecast_days=2&timezone=auto" 2>/dev/null)
		# open-meteo returns local ISO timestamps, which is what date -d in
		# theme-toggle.sh parses
		echo "$location" | jq \
			--argjson sun "${sun:-null}" \
			'{
				latitude: (.latitude | tonumber),
				longitude: (.longitude | tonumber),
				city,
				country: .country_code,
				timezone,
				sunrise: ($sun.daily.sunrise[0] // null),
				sunset: ($sun.daily.sunset[0] // null),
				sunrise_tomorrow: ($sun.daily.sunrise[1] // null),
				sunset_tomorrow: ($sun.daily.sunset[1] // null)
			}' > "$tmp_file"
	fi

	if [ -s "$tmp_file" ]; then
		mv "$tmp_file" "$cache_file"
	else
		rm -f "$tmp_file"
	fi
fi

# a stale cache still answers; an absent one leaves callers to their
# configured fallback coordinates
[ -f "$cache_file" ] && cat "$cache_file"
