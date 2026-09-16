# Render a MET Norway locationforecast reply as waybar's {text, tooltip}.
#
# Arguments, all set by weather.sh:
#   $place    display name for the location
#   $unit     "F" or "C"
#   $speed    "miles" or "km"
#   $updated  preformatted local timestamp
#   $symbols / $texts / $uv   the lookup tables, as files
#
# The tables live beside this file rather than inline because they are 41
# entries each and lifted verbatim from the script this replaces.

def round1: . * 10 | round / 10;

def temp: if . == null then null
  elif $unit == "F" then (. * 9 / 5 + 32 | round1)
  else round1 end;

def speed: if . == null then null
  elif $speed == "miles" then (. * 2.236936 | round1)
  else (. * 3.6 | round1) end;

# Python renders round(x, 1) as "19.0"; jq's tostring gives "19". One
# decimal place, always, or every whole number differs from the original.
def fmt1: if . == null then "None" else
  (. * 10 | round) as $n
  | (($n / 10) | floor) as $w
  | (if $n < 0 then (-$n % 10) else ($n % 10) end) as $f
  | "\($w).\($f)" end;

def unit_label: if $unit == "F" then "°F" else "°C" end;
def speed_label: if $speed == "miles" then "mph" else "km/h" end;

# The symbol covering an entry, from the shortest period stated. MET drops
# to 6-hourly beyond ~2.5 days and those carry no next_1_hours.
def symbol_of:
  .data as $d
  | ($d.next_1_hours.summary.symbol_code //
     $d.next_6_hours.summary.symbol_code //
     $d.next_12_hours.summary.symbol_code // "");

def base_of: if . == "" then "" else split("_")[0] end;
def icon_of: base_of as $b | ($symbols[$b] // "");
def text_of: base_of as $b | ($texts[$b] // "");

# Amount, not probability: MET publishes no PoP.
def precip_of:
  .data as $d
  | if ($d.next_1_hours.details | has("precipitation_amount")) then
      $d.next_1_hours.details.precipitation_amount
    elif ($d.next_6_hours.details | has("precipitation_amount")) then
      $d.next_6_hours.details.precipitation_amount
    else null end;

.properties.timeseries as $ts
| $ts[0] as $now
| $now.data.instant.details as $det
| ($now | symbol_of) as $nowsym

# MET timestamps are UTC. Grouping on the raw string would put evening
# hours on the next day for anyone east of Greenwich, so convert first.
| [ $ts[]
    | (.time | fromdateiso8601) as $epoch
    | {
        day: ($epoch | strflocaltime("%Y-%m-%d")),
        hour: ($epoch | strflocaltime("%H") | tonumber),
        temperature: (.data.instant.details.apparent_air_temperature | temp),
        symbol: symbol_of,
        precipitation: precip_of,
        uv: .data.instant.details.ultraviolet_index_clear_sky,
        min: .data.next_6_hours.details.air_temperature_min,
        max: .data.next_6_hours.details.air_temperature_max
      } ] as $hours

# every other hour: 36 rows is a tooltip, 72 is a wall of text
| [ $hours[] | select(.hour % 2 == 0) ] as $even

| [ $hours[].day ] | unique | .[0:3] as $days_wanted
| [ $days_wanted[] as $day
    | [ $hours[] | select(.day == $day) ] as $of_day
    | [ $of_day[].min | select(. != null) ] as $lows
    | [ $of_day[].max | select(. != null) ] as $highs
    | [ $of_day[].uv | select(. != null) ] as $uvs
    # the symbol for the day is the one covering its middle, not its first
    # hour, which for today is whatever it happens to be doing now
    | ($of_day | sort_by((.hour - 12) | fabs) | .[0]) as $midday
    | "<b>\($day)</b> - \($midday.symbol | text_of) \($midday.symbol | icon_of)" as $header
    | (if ($lows | length) > 0 and ($highs | length) > 0 then
         "⬇️\($lows | min | temp | fmt1)\(unit_label) ⬆️\($highs | max | temp | fmt1)\(unit_label)"
       else "" end) as $span0
    | (if ($uvs | length) > 0 then
         ($uvs | max) as $u
         | if $u >= 6 then
             $span0 + " \($uv[$u | round | tostring] // "")\($u) UV Index"
           else $span0 end
       else $span0 end) as $span
    | [ $even[] | select(.day == $day)
        | "\(.hour): \(.temperature | fmt1)\(unit_label) \(.symbol | text_of) \(.symbol | icon_of)"
          # Python tested the amount for truth, so 0.0 printed nothing. In
          # jq only null and false are falsy, and a "☔0.0mm" on a dry hour
          # is noise the original never showed.
          + (if (.precipitation // 0) > 0 then " ☔\(.precipitation)mm" else "" end) ] as $rows
    | [ $header ] + (if $span == "" then [] else [ $span ] end) + $rows
    | join("\n") ] as $day_blocks

| [ "<b>\($place)</b>:",
    "<b>\($nowsym | text_of) \($nowsym | icon_of)</b>",
    "Feels like: \($det.apparent_air_temperature | temp | fmt1)\(unit_label)",
    "Wind: \($det.wind_speed | speed | fmt1)\(speed_label)",
    "Humidity: \($det.relative_humidity)%" ] as $lines

| {
    text: "\($nowsym | icon_of) \($det.air_temperature | temp | fmt1)\(unit_label)",
    tooltip: (($lines | join("\n")) + "\n\n" + ($day_blocks | join("\n\n"))
              + "\n\nLast update: \($updated)"
              + "\n\nWeather data from MET Norway (met.no)")
  }
