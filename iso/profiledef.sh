#!/usr/bin/env bash
# shellcheck disable=SC2034

iso_name="ashlaros"
iso_label="ASHLAROS_$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y%m)"
iso_publisher="AshlarOS <https://ashlaros.download>"
iso_application="AshlarOS Installer"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH:-$(date +%s)}" +%Y.%m.%d)"
install_dir="arch"
buildmodes=('iso')
# systemd-boot only, which is the whole reason for leaving manjaro-tools:
# it supports GRUB and nothing else. No BIOS mode - the v3 package stack
# already excludes every machine old enough to need one.
bootmodes=('uefi.systemd-boot')
arch="x86_64"
pacman_conf="pacman.conf"
airootfs_image_type="squashfs"
# zstd rather than xz: squashfs decompresses on the page-fault path through
# a single stream, where xz manages ~100MB/s against zstd's ~900MB/s, and
# the live root is read cold on every boot - kernel, systemd, python,
# archinstall, gum. The ISO grows well under a percent for it.
airootfs_image_tool_options=('-comp' 'zstd' '-Xcompression-level' '19' '-b' '1M')
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  # sudo refuses a sudoers.d file that is group- or world-writable, and
  # ignores one it cannot parse - either way the live user has no sudo and
  # the installer it launches cannot touch a disk (#101)
  ["/etc/sudoers.d/live"]="0:0:440"
  ["/root"]="0:0:750"
  # The live session's user. mkarchiso gives uid 1000..59999 homes their
  # owner and fills them from /etc/skel, but only after the packages are
  # in; the executable bit is ours to keep - sway runs this directly, and a
  # non-executable copy is a silent "permission denied" and no installer
  ["/home/live/.automated_script.sh"]="1000:1000:755"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
)
