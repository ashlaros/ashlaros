#!/usr/bin/env bash
#
# skel's sworkstyle config gained icons for the applications whose window
# names upstream's compiled defaults miss: chromium (upstream knows only
# 'Chromium'), ONLYOFFICE, Proton Pass, ntfy Desktop, Gear Lever,
# Tabularis, LXQt Archiver, Storyteller's craft suite, Agent Moshpit, C3,
# the arcade, OpenRA, Open RTS, the printer, Kvantum and qt5ct/qt6ct
# settings, lstopo, qv4l2, qvidcap, xgps and xgpsspeed. Each showed the
# generic fallback. /etc/skel is copied once at account creation, so a
# $HOME made before this keeps the old file. Same shape as 1793629045,
# with a list instead of one entry.
set -uo pipefail

echo "Give the remaining unmatched applications workspace icons in sworkstyle"

config="$HOME/.config/sworkstyle/config.toml"

if [ ! -f "$config" ]; then
    echo "  no sworkstyle config; sworkstyle uses its defaults"
    exit 0
fi

if ! grep -q '^\[matching\]' "$config"; then
    echo "  no [matching] table; not guessing where the entries belong"
    exit 0
fi

# name, then the icon as its UTF-8 bytes, so this file stays ASCII
entries=(
    'chromium'                         $'\xee\x9d\x83'      # dev-chrome
    'ONLYOFFICE'                       $'\xef\x85\x9c'      # fa-file_text
    'proton-pass'                      $'\xef\x82\x84'      # fa-key
    'moe.emmaexe.ntfyDesktop'          $'\xef\x83\xb3'      # fa-bell
    'it.mijorus.gearlever'             $'\xef\x86\xb2'      # fa-cube
    'tabularis'                        $'\xee\x9c\x86'      # dev-database
    'lxqt-archiver'                    $'\xef\x87\x86'      # fa-file_zipper
    'ai.storyteller.artcraft-launcher' $'\xee\xbf\x8c'      # fa-palette
    'ai.storyteller.effectcraft'       $'\xf3\xb1\x9c\x97'  # md-movie_star
    'ai.storyteller.filmcraft'         $'\xef\x80\x88'      # fa-film
    'ai.storyteller.gridcraft'         $'\xef\x83\x8e'      # fa-table
    'ai.storyteller.pdfcraft'          $'\xef\x87\x81'      # fa-file_pdf_o
    'ai.storyteller.vectorcraft'       $'\xee\xba\x92'      # fa-vector_square
    'ai.storyteller.wordcraft'         $'\xf3\xb0\x88\xac'  # md-file_word
    'ai.storyteller.photocraft'        $'\xef\x82\x83'      # fa-camera_retro
    'agent-moshpit'                    $'\xee\xb8\x8d'      # fa-robot
    'c3-desktop'                       $'\xef\x83\xa8'      # fa-sitemap
    'AshlarOS Arcade'                  $'\xef\x84\x9b'      # fa-gamepad
    'OpenRA'                           $'\xf3\xb0\xb4\xba'  # md-tank
    'g2-client'                        $'\xf3\xb0\x9e\x87'  # md-sword_cross
    'system-config-printer'            $'\xef\x80\xaf'      # fa-print
    'kvantummanager'                   $'\xf3\xb0\xa2\xb5'  # md-palette_swatch
    'qt5ct'                            $'\xee\xa1\xbd'      # dev-qt
    'qt6ct'                            $'\xee\xa1\xbd'      # dev-qt
    'lstopo'                           $'\xef\x8b\x9b'      # fa-microchip
    'qv4l2'                            $'\xef\x80\xbd'      # fa-video_camera
    'qvidcap'                          $'\xef\x80\xbd'      # fa-video_camera
    'xgps'                             $'\xee\x89\x88'      # fae-gps
    'xgpsspeed'                        $'\xf3\xb0\x93\x85'  # md-speedometer
)

lines=""
kept=0
for ((i = 0; i < ${#entries[@]}; i += 2)); do
    name=${entries[i]}
    # an entry the user wrote themselves wins
    if grep -q "^[[:space:]]*['\"]${name//./\\.}['\"][[:space:]]*=" "$config"; then
        kept=$((kept + 1))
        continue
    fi
    lines+="'$name' = '${entries[i + 1]}'"$'\n'
done

((kept)) && echo "  $kept already had an entry, leaving those alone"

if [ -z "$lines" ]; then
    exit 0
fi

tmp=$(mktemp "${config}.XXXXXX") || exit 1
# ENVIRON rather than -v: -v would interpret backslashes in the value
LINES_TO_ADD=${lines%$'\n'} awk '{ print } /^\[matching\]/ { print ENVIRON["LINES_TO_ADD"] }' \
    "$config" >"$tmp" || { rm -f "$tmp"; exit 1; }
chmod --reference="$config" "$tmp" 2>/dev/null || true
mv -- "$tmp" "$config"
echo "  added $(printf '%s' "$lines" | grep -c .) entries under [matching]"
