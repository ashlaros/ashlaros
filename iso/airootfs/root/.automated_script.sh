#!/usr/bin/env bash
#
# Live ISO installer script: set the console up, run the configurator,
# then hand off to the dashboard.
#
# Run inside a terminal window by sway at startup.
#
# The stream contract matters:
#   - stdout is teed to the log with the CSI sequences stripped, and to the tty
#   - CLICOLOR_FORCE/FORCE_COLOR so gum still emits colour with stdout piped
#   - COLUMNS/LINES so gum picks up the real terminal size
set -uo pipefail


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
#
# --no-block, and a timeout on the wait. pacman-init is ordered
# After=time-sync.target, and systemd-time-wait-sync.service holds that
# target with TimeoutStartSec=infinity - so on a machine with no network
# the clock never syncs, the target never arrives, and a blocking start
# here waits for it forever. Measured: the ISO sat on the login banner
# with the installer never drawn, which reads as a hung boot rather than
# as a missing network.
#
# Waiting at all is worth it: a keyring that is not yet populated fails
# every signature check. But an install served entirely from the medium's
# own cache needs no keyring at all, so a timeout is the right answer and
# carrying on is better than stopping.
systemctl start --no-block pacman-init.service 2>/dev/null
for _ in $(seq 1 30); do
  systemctl is-active --quiet pacman-init.service && break
  sleep 1
done

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
  ashlaros-install
