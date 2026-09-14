#!/bin/bash
# Install Google Docs or Office 365 as web apps: own window, own icon,
# launchable from rofi like anything else.
#
# This exists because the desktop otherwise cannot open a .docx at all -
# no suite, no viewer. LibreOffice is 147 MB and the only thing that
# faithfully round-trips Office formats, so it is an optdepend for people
# who need that; this is the five-megabyte answer for people who just got
# sent a spreadsheet.
#
# Why we write the manifests instead of fetching theirs: firefoxpwa needs
# a parseable web app manifest, and neither provider serves one to a
# logged-out fetch. docs.google.com/manifest.json is a 404 and
# office.com/manifest.json answers 403 in an HTML body, so
# `firefoxpwa site install <page-url>` fails with "expected value at line
# 1 column 1". Ours are minimal and name the same start URLs a browser
# would navigate to.
set -euo pipefail

command -v firefoxpwa >/dev/null || {
    echo "firefoxpwa is not installed." >&2
    exit 1
}

say() { printf '  %s\n' "$*"; }

install_site() {
    name=$1 start=$2 scope=$3

    if firefoxpwa profile list 2>/dev/null | grep -qF "$name"; then
        say "$name is already installed."
        return 0
    fi

    dir=$(mktemp -d)
    # trap inside a function would clobber the outer one; clean up by hand
    cat > "$dir/manifest.json" <<EOF
{
  "name": "$name",
  "short_name": "$name",
  "start_url": "$start",
  "scope": "$scope",
  "display": "standalone"
}
EOF

    # firefoxpwa fetches the manifest over HTTP rather than reading a
    # path, so serve the one we just wrote to ourselves for a moment.
    # The port is chosen by the kernel and printed by the server itself:
    # `python3 -m http.server 0` reports nothing we can parse.
    python3 - "$dir" <<'PYEOF' &
import http.server, socketserver, sys, functools, pathlib
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=sys.argv[1])
with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
    pathlib.Path(sys.argv[1], "port").write_text(str(httpd.server_address[1]))
    httpd.serve_forever()
PYEOF
    server=$!

    for _ in 1 2 3 4 5 6 7 8 9 10; do
        [ -s "$dir/port" ] && break
        sleep 0.3
    done
    port=$(cat "$dir/port" 2>/dev/null || true)

    if [ -z "${port:-}" ]; then
        kill "$server" 2>/dev/null || true
        rm -rf "$dir"
        say "Could not start the local manifest server."
        return 1
    fi

    say "Installing $name…"
    firefoxpwa site install "http://127.0.0.1:$port/manifest.json" \
        --document-url "$start" \
        --name "$name" \
        --start-url "$start" || true

    # firefoxpwa records the URL it fetched the manifest from, and ours
    # was a port that stops existing a line later. Left alone, every
    # `firefoxpwa site update` dies on "Connection refused" against a
    # loopback address; --no-manifest-updates is per-invocation and not
    # persisted, so the stored URL is what has to change. Rewriting it to
    # the site itself makes an update attempt fail against the real site,
    # which is both honest and what a user would expect to see.
    config="${XDG_DATA_HOME:-$HOME/.local/share}/firefoxpwa/config.json"
    [ -f "$config" ] && python3 - "$config" "$port" "$start" <<'PYEOF'
import json, sys, pathlib
path, port, start = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
data = json.loads(path.read_text())
stale = f"http://127.0.0.1:{port}/manifest.json"
for site in data.get("sites", {}).values():
    if site.get("config", {}).get("manifest_url") == stale:
        site["config"]["manifest_url"] = start
path.write_text(json.dumps(data, indent=2))
PYEOF

    kill "$server" 2>/dev/null || true
    rm -rf "$dir"
}

case "${1:-}" in
    docs | office) ;;
    *)
        echo "usage: ${0##*/} docs|office" >&2
        exit 2
        ;;
esac

# Per-user and ~300 MB: this cannot happen at package build time, which is
# why the whole thing is an explicit action rather than a postinstall or
# an autostart entry racing the network at every login. After the argument
# check, so a typo does not cost a 300 MB download.
if [ ! -d "${XDG_DATA_HOME:-$HOME/.local/share}/firefoxpwa/runtime" ]; then
    say "Downloading the web app runtime (~300 MB, once per user)…"
    firefoxpwa runtime install
fi

case "$1" in
    docs)
        install_site "Google Docs" "https://docs.google.com/document/" "https://docs.google.com/"
        install_site "Google Sheets" "https://docs.google.com/spreadsheets/" "https://docs.google.com/"
        install_site "Google Slides" "https://docs.google.com/presentation/" "https://docs.google.com/"
        ;;
    office)
        install_site "Microsoft 365" "https://www.microsoft365.com/" "https://www.microsoft365.com/"
        ;;
esac

say "Done. They are in the launcher; the first run asks you to sign in."
