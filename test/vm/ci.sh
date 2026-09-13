#!/usr/bin/env bash
# Boot a freshly built ISO and drive the installer, for CI.
#
# The interactive harness (`run.sh`) exists to look at a running system;
# this exists to answer one question with an exit status. It reuses the
# same container, the same boot.sh and the same install.py, because a test
# that drove the installer differently from the way a person does would
# stop being evidence about the thing people run.
#
#   ci.sh boot    <iso>   the ISO reaches the installer's first screen
#   ci.sh install <iso>   ... and installing it produces a system that boots
#
# Screenshots and the serial log land in $WORKSPACE/out for upload, whether
# or not the run passed: a failure with no picture of the screen is a
# failure nobody can diagnose.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

mode="${1:?usage: ci.sh boot|install <iso>}"
iso="${2:?usage: ci.sh boot|install <iso>}"

# Workspace AND container are per-mode. The two tests are separate jobs in
# CI, but they share a machine whenever anyone runs both locally - and
# `run.sh` defaults both names, so the second run silently `docker rm -f`s
# the first one's VM. Found by doing exactly that mid-install.
export WORKSPACE="${WORKSPACE:-/tmp/ashlaros-vm-$mode}"
export CONTAINER="${CONTAINER:-ashlaros-vm-$mode}"

mkdir -p "$WORKSPACE/out"
cp "$iso" "$WORKSPACE/ashlaros.iso"

cleanup() {
  # the VM is killed whatever happened, or the job hangs until the
  # workflow's own timeout - a far less readable failure
  "$here/run.sh" stop >/dev/null 2>&1 || true
}
trap cleanup EXIT

case "$mode" in
boot)
  # Reaching the first screen exercises the whole boot path: systemd-boot
  # finds the loader entry, the kernel and squashfs come up, and the
  # autostart runs the configurator. A broken import in the orchestrator,
  # or an ISO with no bootable EFI partition, cannot get here.
  SECONDS_TO_RUN=1800 "$here/run.sh" install-start
  "$here/run.sh" shot ci-installer >/dev/null
  echo "== the ISO reaches the installer"
  ;;
install)
  SECONDS_TO_RUN=7200 "$here/run.sh" install
  # install.py takes the offered reboot, so the same VM comes back up on
  # the disk it just wrote. Waiting for it here rather than trusting the
  # installer's own "done" is the point: an install that completes and
  # produces an unbootable system is the failure worth catching.
  "$here/run.sh" wait-installed 5400
  "$here/run.sh" shot ci-installed >/dev/null
  echo "== the installed system boots"
  ;;
*)
  echo "usage: ci.sh boot|install <iso>" >&2
  exit 2
  ;;
esac
