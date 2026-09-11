#!/usr/bin/env bash
#
# Build the machine the screenshots are taken on: an Arch container with our
# repository trusted and ashlaros-settings installed, which is what makes
# the picture show the real desktop rather than bare sway.
set -euo pipefail

: "${ASHLAROS_REPO_URL:=https://packages.ashlaros.download}"
: "${SHOT_USER:=ashlar}"

pacman -Sy --noconfirm --needed archlinux-keyring >/dev/null
# python-requests is only an optdepend of ashlaros-settings, and without it
# the bar's weather module renders as an error
pacman -S --noconfirm --needed curl python-yaml python-requests >/dev/null

curl -fsSL "$ASHLAROS_REPO_URL/ashlaros.gpg" -o /tmp/ashlaros.gpg
pacman-key --init
pacman-key --add /tmp/ashlaros.gpg
pacman-key --lsign-key "$(gpg --show-keys --with-colons /tmp/ashlaros.gpg | awk -F: '/^fpr:/{print $10; exit}')"

# cachyos first: the settings package depends on plain Arch packages, but the
# repository it comes from is layered over cachyos and pacman takes the first
# repository carrying a package
cat >>/etc/pacman.conf <<EOF

[cachyos]
SigLevel = Never
Server = https://mirror.cachyos.org/repo/x86_64/cachyos

[ashlaros]
Server = $ASHLAROS_REPO_URL/\$arch
EOF

pacman -Sy --noconfirm >/dev/null
pacman -S --noconfirm --needed ashlaros-settings >/dev/null

# waybar exits immediately without one: "Cannot spawn a message bus without
# a machine-id". A container image ships none, a real install gets it from
# systemd's first boot.
dbus-uuidgen --ensure=/etc/machine-id

# sway refuses to run as root, and the shot should render a user's session
# anyway - skel is what a real first login copies
# zsh, because that is the shell the settings package configures and a bash
# prompt in the picture would advertise a desktop we do not ship
useradd -m -s /bin/zsh "$SHOT_USER"
install -d -o "$SHOT_USER" -g "$SHOT_USER" "${OUT_DIR:-/out}"
# no logind in a container, so nothing creates the runtime dir wayland needs
install -d -m 700 -o "$SHOT_USER" -g "$SHOT_USER" "/run/user/$(id -u "$SHOT_USER")"
# the bar's wob pipe lands here; a first login would have made it already
install -d -o "$SHOT_USER" -g "$SHOT_USER" "/home/$SHOT_USER/.cache"

echo "ready: $(pacman -Q ashlaros-settings)"
