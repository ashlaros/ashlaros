#!/bin/sh
# Approximate location and today's sun times, cached for the day.
#
# manjaro-sway proxied this through a cloudflare worker that read the
# request's own geo-ip data and computed sunrise/sunset. We run no such
# worker, so the location comes from geojs.io (no key, no account, no rate
# limit - ipapi.co answers 429 to an unauthenticated caller) and the sun
# times from MET Norway, already the source the weather module uses.
# MET asks callers to identify themselves - see weather.py - so the same
# User-Agent goes on these requests.
# Consumers - sunset.sh and theme-toggle.sh - read .latitude/.longitude/
# .city/.sunrise/.sunset/.sunrise_tomorrow/.sunset_tomorrow, so this emits
# exactly those keys.
set -u

# MET wants to know who is calling and how to reach them; see weather.py.
USER_AGENT="ashlaros-weather/1.0 github.com/ashlaros/ashlaros"

sun_for() {
	curl -fsSL --max-time 10 -H "User-Agent: $USER_AGENT" \
		"https://api.met.no/weatherapi/sunrise/3.0/sun?lat=$1&lon=$2&date=$3&offset=$4" \
		2>/dev/null
}

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
		# MET's sunrise API answers for one date per call, where open-meteo
		# returned two days at once - hence two requests. The offset comes
		# from geojs's timezone so the timestamps come back offset-aware,
		# which is the form date -d in theme-toggle.sh parses.
		offset=$(TZ="$(echo "$location" | jq -r '.timezone // "UTC"')" date +%:z)
		sun_today=$(sun_for "$latitude" "$longitude" "$(date +%Y-%m-%d)" "$offset")
		sun_tomorrow=$(sun_for "$latitude" "$longitude" "$(date -d tomorrow +%Y-%m-%d)" "$offset")

		echo "$location" | jq \
			--argjson today "${sun_today:-null}" \
			--argjson tomorrow "${sun_tomorrow:-null}" \
			'{
				latitude: (.latitude | tonumber),
				longitude: (.longitude | tonumber),
				city,
				country: .country_code,
				timezone,
				sunrise: ($today.properties.sunrise.time // null),
				sunset: ($today.properties.sunset.time // null),
				sunrise_tomorrow: ($tomorrow.properties.sunrise.time // null),
				sunset_tomorrow: ($tomorrow.properties.sunset.time // null)
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
