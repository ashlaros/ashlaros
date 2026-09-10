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
  ["/root"]="0:0:750"
  ["/root/.automated_script.sh"]="0:0:755"
  ["/usr/local/bin/choose-mirror"]="0:0:755"
)
