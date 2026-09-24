#!/bin/sh
# The waybar weather module.
#
# Replaces a 386-line python3 script whose only third-party import was
# requests. curl and jq are both already here, so this removes
# python-requests from the tree rather than merely moving code around.
#
# MET Norway asks three things of a client in return for a free, keyless
# API, and all three are obligations rather than courtesies - "if we cannot
# contact you in case of problems, you risk being blocked without warning":
#
#   - identify yourself in User-Agent, with a contact address
#   - cache, and revalidate with If-Modified-Since rather than refetching
#   - do not schedule on the hour; their data updates continuously
#
# MET publishes no geocoding API, so a typed city name is resolved by
# open-meteo. 'auto' asks our own worker instead, which reads the geo data
# Cloudflare attached at its edge - the machine's IP goes to us rather than
# to a third party.

set -eu

USER_AGENT="ashlaros-weather/1.0 github.com/ashlaros/ashlaros"
FORECAST_URL="https://api.met.no/weatherapi/locationforecast/2.0/complete"
GEO_URL="${ASHLAROS_GEO_URL:-https://ashlaros.download/geo}"
GEOCODE_URL="https://geocoding-api.open-meteo.com/v1/search"

here=$(dirname "$(readlink -f "$0")")
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/ashlaros"
cache_file="$cache_dir/weather.json"
response_cache="$cache_dir/weather-response.json"

# ini, one sed: `city = Frankfurt am Main` has to survive with its spaces
config="${XDG_CONFIG_HOME:-$HOME/.config}/weather.cfg"
conf_get() {
	[ -r "$config" ] || return 0
	sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*\(.*[^[:space:]]\)[[:space:]]*$/\1/p" \
		"$config" | head -1
}

city=$(conf_get city)
temperature=$(conf_get temperature)
distance=$(conf_get distance)

: "${city:=auto}"
: "${temperature:=C}"
: "${distance:=km}"

usage() {
	echo "usage: ${0##*/} [-t C|F] [-d km|miles] [-c <city>|auto]" >&2
	exit 2
}

while [ $# -gt 0 ]; do
	case $1 in
	-t | --temperature) temperature=${2:?}; shift 2 ;;
	-d | --distance) distance=${2:?}; shift 2 ;;
	-c | --city) city=${2:?}; shift 2 ;;
	*) usage ;;
	esac
done

case $temperature in C | F) ;; *) usage ;; esac
case $distance in km | miles) ;; *) usage ;; esac

# Serve whatever was rendered last. The bar showing an hour-old forecast
# beats the bar showing an error because a train went through a tunnel.
# Through jq -c, because a cache written before the render below was
# compact is pretty-printed, and waybar cannot read that (see there).
fallback() {
	if [ -r "$cache_file" ] && jq -c . "$cache_file" 2>/dev/null; then
		exit 0
	fi
	echo "$1" >&2
	exit 1
}

if [ "$city" = auto ]; then
	geo=$(curl -fsSL --max-time 10 -A "$USER_AGENT" "$GEO_URL" 2>/dev/null) ||
		fallback "weather: cannot reach the geo endpoint"
	latitude=$(printf '%s' "$geo" | jq -r '.latitude')
	longitude=$(printf '%s' "$geo" | jq -r '.longitude')
	place=$(printf '%s' "$geo" | jq -r '.city // ""')
else
	geo=$(curl -fsSL --max-time 10 -G -A "$USER_AGENT" \
		--data-urlencode "name=$city" --data-urlencode "count=1" \
		"$GEOCODE_URL" 2>/dev/null) ||
		fallback "weather: cannot reach the geocoder"
	if [ "$(printf '%s' "$geo" | jq -r '.results | length')" = 0 ]; then
		fallback "weather: no such place: $city"
	fi
	latitude=$(printf '%s' "$geo" | jq -r '.results[0].latitude')
	longitude=$(printf '%s' "$geo" | jq -r '.results[0].longitude')
	place=$(printf '%s' "$geo" | jq -r '.results[0].name')
fi

# MET rounds coordinates itself and asks clients not to send more precision
# than they need; four places is ~11 m.
latitude=$(printf '%.4f' "$latitude")
longitude=$(printf '%.4f' "$longitude")

# Revalidate rather than refetch. A 304 costs MET almost nothing and us a
# round trip, and skipping it is the behaviour they block for.
last_modified=""
[ -r "$response_cache" ] &&
	last_modified=$(jq -r '.last_modified // ""' "$response_cache" 2>/dev/null)

headers=$(mktemp)
body=$(mktemp)
trap 'rm -f "$headers" "$body"' EXIT

set -- -fsSL --max-time 10 -A "$USER_AGENT" -D "$headers" -o "$body"
[ -n "$last_modified" ] && set -- "$@" -H "If-Modified-Since: $last_modified"

if ! curl "$@" "$FORECAST_URL?lat=$latitude&lon=$longitude" 2>/dev/null; then
	fallback "weather: cannot reach met.no"
fi

status=$(awk '/^HTTP\//{c=$2} END{print c}' "$headers" | tr -d '\r')

if [ "$status" = 304 ]; then
	forecast=$(jq -c '.body' "$response_cache")
else
	forecast=$(cat "$body")
	new_lm=$(awk 'BEGIN{IGNORECASE=1} /^[Ll]ast-[Mm]odified:/ {sub(/^[^:]*: */, ""); print}' \
		"$headers" | tr -d '\r' | head -1)
	mkdir -p "$cache_dir"
	printf '%s' "$forecast" |
		jq --arg lm "$new_lm" '{body: ., last_modified: $lm}' >"$response_cache"
fi

# %c with the zone. Python's datetime.now() is naive, so its %Z expanded to
# nothing and left the separator behind as a trailing space.
updated=$(date "+%c")

# -c: waybar parses a custom module's output line by line, one JSON object
# per line. Pretty-printed, the first line is a lone "{" and waybar logs
# "Error parsing JSON: Line 1, Column 2" on every poll and shows nothing.
rendered=$(printf '%s' "$forecast" | jq -c \
	--arg place "$place" \
	--arg unit "$temperature" \
	--arg speed "$distance" \
	--arg updated "$updated" \
	--slurpfile symbols_f "$here/weather-symbols.json" \
	--slurpfile texts_f "$here/weather-text.json" \
	--slurpfile uv_f "$here/weather-uv.json" \
	'($symbols_f[0]) as $symbols | ($texts_f[0]) as $texts | ($uv_f[0]) as $uv
	 | '"$(cat "$here/weather.jq")"'' 2>/dev/null) ||
	fallback "weather: could not render the forecast"

mkdir -p "$cache_dir"
printf '%s' "$rendered" >"$cache_file"
printf '%s\n' "$rendered"
