#!/bin/sh
# Approximate location and today's sun times, cached for the day.
#
# One call to our own worker, which reads the geo data Cloudflare already
# attached to the request at its edge and computes the sun times there. No
# third party sees the machine's IP: previously this told get.geojs.io,
# and the weather module told it again on every refresh.
#
# Consumers - sunset.sh, theme-toggle.sh and weather.sh - read .latitude/
# .longitude/.city/.sunrise/.sunset/.sunrise_tomorrow/.sunset_tomorrow, and
# the worker answers with exactly those keys, so this passes the body
# through.
set -u

geo_url="${ASHLAROS_GEO_URL:-https://ashlaros.download/geo}"

# A place chosen in Settings -> Location wins, and is answered without
# asking anyone: the file holds coordinates, and the sun times are the
# worker's own NOAA equation (worker/src/geo.js) in jq, in the same shape.
# Not cached - it is one jq call.
location="${XDG_CONFIG_HOME:-$HOME/.config}/ashlaros/location"
location_get() {
	sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\(.*[^[:space:]]\)[[:space:]]*$/\1/p" \
		"$location" | head -1
}

if [ -r "$location" ]; then
	jq -n \
		--argjson lat "$(location_get latitude)" \
		--argjson lon "$(location_get longitude)" \
		--arg name "$(location_get name)" '
		def rad: . * (1 | atan) / 45;
		# the local calendar date at 12:00 UTC, as the worker takes it
		def day($days): now + $days * 86400 | localtime | .[3:6] = [12, 0, 0] | mktime;
		# 2026-09-11T06:45+02:00: theme-toggle.sh parses these with date -d,
		# so the zone offset has to be there, as it is in the worker
		def stamp: (. - 2440587.5) * 86400 | floor
			| strflocaltime("%Y-%m-%dT%H:%M%z")
			| sub("(?<h>[0-9]{2})(?<m>[0-9]{2})$"; "\(.h):\(.m)");
		def sun($date):
			(($date / 86400 + 2440587.5 - 2451545.0 + 0.0008) | floor) as $julian
			| ($julian - $lon / 360) as $noon
			| (357.5291 + 0.98560028 * $noon | fmod(.; 360)) as $m
			| (1.9148 * ($m | rad | sin) + 0.02 * (2 * $m | rad | sin)
				+ 0.0003 * (3 * $m | rad | sin)) as $centre
			| ($m + $centre + 180 + 102.9372 | fmod(.; 360)) as $ecliptic
			| (2451545.0 + $noon + 0.0053 * ($m | rad | sin)
				- 0.0069 * (2 * $ecliptic | rad | sin)) as $transit
			| (($ecliptic | rad | sin) * (23.4397 | rad | sin) | asin) as $declination
			| (((-0.833 | rad | sin) - ($lat | rad | sin) * ($declination | sin))
				/ (($lat | rad | cos) * ($declination | cos))) as $hour
			# polar day or polar night: no rise or set to report
			| if $hour > 1 or $hour < -1 then {sunrise: null, sunset: null}
			else (($hour | acos) / (1 | rad) / 360) as $half
				| {sunrise: ($transit - $half | stamp), sunset: ($transit + $half | stamp)}
			end;
		if ($lat | type) != "number" or ($lon | type) != "number"
			or $lat < -90 or $lat > 90 or $lon < -180 or $lon > 180
		then error("coordinates out of range") else . end
		| sun(day(0)) as $today | sun(day(1)) as $tomorrow
		| {
			latitude: $lat,
			longitude: $lon,
			city: (if $name == "" then null else $name end),
			sunrise: $today.sunrise,
			sunset: $today.sunset,
			sunrise_tomorrow: $tomorrow.sunrise,
			sunset_tomorrow: $tomorrow.sunset
		}' 2>/dev/null && exit 0
	# a broken file must not take the night light and the weather with it
	echo "geoip: no usable coordinates in $location, guessing instead" >&2
fi

cache_file="$HOME/.cache/geoip"
cache_time=$(date -r "$cache_file" +%s 2>/dev/null || echo 0)
six_hours_ago=$(date -d 'now - 6 hour' +%s)
start_of_day=$(date -d '00:00' +%s)

if [ ! -f "$cache_file" ] || [ "$cache_time" -lt "$six_hours_ago" ] || [ "$cache_time" -lt "$start_of_day" ]; then
	mkdir -p "$(dirname "$cache_file")"
	tmp_file=$(mktemp "${cache_file}.tmp.XXXXXX") || exit 1

	# The worker already returns the shape consumers read, so this only
	# checks that it is that shape before replacing a working cache: a 503
	# from an edge without geo data must not blank out yesterday's answer.
	curl -fsSL --max-time 10 "$geo_url" 2>/dev/null \
		| jq -e 'select(.latitude != null and .longitude != null)' > "$tmp_file" 2>/dev/null

	if [ -s "$tmp_file" ]; then
		mv "$tmp_file" "$cache_file"
	else
		rm -f "$tmp_file"
	fi
fi

# a stale cache still answers; an absent one leaves callers to their
# configured fallback coordinates
[ -f "$cache_file" ] && cat "$cache_file"
