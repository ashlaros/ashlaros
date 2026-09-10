#!/usr/bin/env python
"""Script for the Waybar weather module.

manjaro-sway called a cloudflare worker that talked to open-meteo and
rendered the tooltip server-side. AshlarOS runs no such service, so the
rendering that used to live in the worker lives here: the module calls
open-meteo directly (no key, no account) and emits the same
{"text", "tooltip"} shape waybar expects.
"""

import argparse
import configparser
import json
import locale
import sys
import urllib.parse
from datetime import date, datetime
from os import path, environ, makedirs

import requests

WMO_EMOJI = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌧️", 53: "🌧️", 55: "🌧️", 56: "🌧️", 57: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌧️", 67: "🌧️",
    71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️",
    80: "🌧️", 81: "🌧️", 82: "🌧️", 85: "❄️", 86: "❄️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}

WMO_TEXT = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Slight or moderate thunderstorm",
    96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

# above 6 the index is worth calling out; below it the line is noise
UV_EMOJI = {3: "😎", 4: "😎", 5: "😎", 6: "🫠", 7: "🫠",
            8: "🥵", 9: "🥵", 10: "🥵", 11: "🥵"}

config_path = path.join(
    environ.get('XDG_CONFIG_HOME') or
    path.join(environ['HOME'], '.config'),
    "weather.cfg"
)

config = configparser.ConfigParser()
config.read(config_path)

# see https://docs.python.org/3/library/locale.html#background-details-hints-tips-and-caveats
locale.setlocale(locale.LC_ALL, "")
current_locale, _ = locale.getlocale(locale.LC_NUMERIC)
city = config.get('DEFAULT', 'city', fallback='auto')
temperature = config.get('DEFAULT', 'temperature', fallback='C')
distance = config.get('DEFAULT', 'distance', fallback='km')

if current_locale == "en_US":
    temperature = temperature or "F"
    distance = distance or "miles"

parser = argparse.ArgumentParser(description='Waybar weather module')
parser.add_argument('-t', '--temperature', default=temperature, choices=['C', 'F'],
                    help='Temperature unit: C (Celsius) or F (Fahrenheit)')
parser.add_argument('-d', '--distance', default=distance, choices=['km', 'miles'],
                    help='Distance unit: km or miles')
parser.add_argument('-c', '--city', default=city,
                    help='City name or "auto" for automatic detection')
args = parser.parse_args()

temperature = args.temperature.upper()
distance = args.distance.lower()
city = args.city

temperature_unit = "fahrenheit" if temperature == "F" else "celsius"
wind_speed_unit = "mph" if distance == "miles" else "kmh"

cache_dir = path.join(
    environ.get('XDG_CACHE_HOME') or path.join(environ['HOME'], '.cache'),
    'ashlaros'
)
cache_file = path.join(
    cache_dir,
    f"weather-{urllib.parse.quote(city, safe='')}-{temperature_unit}-{wind_speed_unit}-{date.today()}.json"
)


def resolve_location(name):
    """Coordinates and display name for a city, or for this machine's IP.

    'auto' asks geojs.io where the request came from, the same thing the
    worker used to read off the request itself; anything else is geocoded
    by open-meteo. geojs rather than ipapi.co: the latter answers 429 to
    an unauthenticated caller.
    """
    if name == 'auto':
        result = requests.get(
            "https://get.geojs.io/v1/ip/geo.json", timeout=10).json()
        return result['latitude'], result['longitude'], result['city']

    result = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": name, "count": 1},
        timeout=10,
    ).json()
    if not result.get('results'):
        raise ValueError(f"no such place: {name}")
    place = result['results'][0]
    return place['latitude'], place['longitude'], place['name']


def render(place, data):
    current, units = data['current'], data['current_units']
    code = current['weather_code']
    # at night a clear sky is a moon, not a sun
    night = current['is_day'] == 0
    icon = "🌙" if night and code == 0 else WMO_EMOJI.get(code, "")

    lines = [
        f"<b>{place}</b>:",
        f"<b>{WMO_TEXT.get(code, '')} {WMO_EMOJI.get(code, '')}</b>",
        f"Feels like: {current['apparent_temperature']}{units['apparent_temperature']}",
        f"Wind: {current['wind_speed_10m']}{units['wind_speed_10m']}",
        f"Humidity: {current['relative_humidity_2m']}{units['relative_humidity_2m']}",
    ]

    hourly, hourly_units = data['hourly'], data['hourly_units']
    # every other hour: 36 rows is a tooltip, 72 is a wall of text
    hours = [
        {
            'time': hourly['time'][i],
            'hour': datetime.fromisoformat(hourly['time'][i]).hour,
            'temperature': hourly['apparent_temperature'][i],
            'code': hourly['weather_code'][i],
            'precipitation': hourly['precipitation_probability'][i],
            'is_day': hourly['is_day'][i],
        }
        for i in range(len(hourly['time']))
    ]
    hours = [h for h in hours if h['hour'] % 2 == 0]

    daily, daily_units = data['daily'], data['daily_units']
    days = []
    for i, day in enumerate(daily['time']):
        day_code = daily['weather_code'][i]
        uv = daily['uv_index_clear_sky_max'][i]
        header = f"<b>{day}</b> - {WMO_TEXT.get(day_code, '')} {WMO_EMOJI.get(day_code, '')}"
        span = (
            f"⬇️{daily['apparent_temperature_min'][i]}{daily_units['apparent_temperature_min']}"
            f" ⬆️{daily['apparent_temperature_max'][i]}{daily_units['apparent_temperature_max']}"
        )
        if uv is not None and uv >= 6:
            span += f" {UV_EMOJI.get(round(uv), '')}{uv} UV Index"

        rows = []
        for hour in (h for h in hours if h['time'].startswith(day)):
            hour_icon = ("🌙" if hour['is_day'] == 0 and hour['code'] == 0
                         else WMO_EMOJI.get(hour['code'], ""))
            row = (
                f"{hour['hour']}: {hour['temperature']}{hourly_units['apparent_temperature']}"
                f" {WMO_TEXT.get(hour['code'], '')} {hour_icon}"
            )
            if hour['precipitation']:
                row += f" ☔{hour['precipitation']}%"
            rows.append(row)

        days.append("\n".join([header, span, *rows]))

    updated = datetime.now().strftime("%c")
    return {
        "text": f"{icon} {current['temperature_2m']}{units['temperature_2m']}",
        "tooltip": "\n".join(lines) + "\n\n" + "\n\n".join(days)
                   + f"\n\nLast update: {updated}\n\nPowered by Open-Meteo.com",
    }


try:
    latitude, longitude, place = resolve_location(city)
    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "temperature_unit": temperature_unit,
            "wind_speed_unit": wind_speed_unit,
            "timezone": "auto",
            "current": "temperature_2m,wind_speed_10m,weather_code,"
                       "apparent_temperature,relative_humidity_2m,is_day",
            "daily": "weather_code,apparent_temperature_min,"
                     "apparent_temperature_max,uv_index_clear_sky_max",
            "hourly": "apparent_temperature,weather_code,"
                      "precipitation_probability,is_day",
            "forecast_days": 3,
            "forecast_hours": 72,
        },
        timeout=10,
    ).json()
    weather = render(place, forecast)
    makedirs(cache_dir, exist_ok=True)
    with open(cache_file, 'w') as f:
        json.dump(weather, f)
except (
    requests.exceptions.HTTPError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    KeyError,
    ValueError,
) as err:
    if path.exists(cache_file):
        with open(cache_file) as f:
            weather = json.load(f)
    else:
        print(str(err), file=sys.stderr)
        sys.exit(1)

print(json.dumps(weather))
