#!/usr/bin/env bash
#
# Live ISO entry point on tty1: set the console up, run the configurator,
# then hand off to the dashboard, which owns the screen while the
# orchestrator installs.
#
# The stream contract matters:
#   - stdout is teed to the log with the CSI sequences stripped, and to the tty
#   - stderr goes straight to /dev/tty, because gum draws its TUI there
#   - CLICOLOR_FORCE/FORCE_COLOR so gum still emits colour with stdout piped
#   - COLUMNS/LINES so gum picks up the real terminal size
set -uo pipefail

[[ $(tty) == /dev/tty1 ]] || exit 0

export ASHLAROS_PATH=/usr/share/ashlaros
export ASHLAROS_INSTALL_LOG_FILE=/var/log/ashlaros-install.log

mkdir -p /var/log /run/ashlaros-install
touch "$ASHLAROS_INSTALL_LOG_FILE"

COLUMNS=$(tput cols)
LINES=$(tput lines)
export COLUMNS LINES
exec > >(tee >(sed -u 's/\x1b\[[0-9;?]*[A-Za-z]//g' >>"$ASHLAROS_INSTALL_LOG_FILE") 2>/dev/null) 2>/dev/tty
export CLICOLOR_FORCE=1
export FORCE_COLOR=1

# The keyring has to be usable before the installer fetches anything from
# the cachyos or ashlaros repositories.
systemctl is-active --quiet pacman-init.service ||
  systemctl start pacman-init.service 2>/dev/null

cd /root || exit 1

# The one place the mark can animate without repeating: the configurator's
# clear_logo runs before every form and the dashboard redraws each second,
# so both of those stay static. Drawn on the tty directly, ahead of the
# stdout tee, because the frames are overdrawn - the log wants the result,
# not twelve copies of a wall being built.
ashlaros-logo-animate 2>/dev/null >/dev/tty

ashlaros-configurator || exit $?

ASHLAROS_DASHBOARD_TTY=$(tty)
export ASHLAROS_DASHBOARD_TTY
rm -f /run/ashlaros-install/state.json
ashlaros-install-dashboard \
  "$ASHLAROS_INSTALL_LOG_FILE" \
  /run/ashlaros-install/state.json \
  -- \
  ashlaros-install \
  --config /root/user_configuration.json \
  --creds /root/user_credentials.json
