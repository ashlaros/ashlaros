#!/usr/bin/env bash
# Pull the kernel, initramfs and DTB off the image's FAT boot partition so
# QEMU can be handed them directly.
#
# Taken from manjaro-sway's ci/extract-rpi-kernel.sh, which solved this
# first. The load-bearing trick is mtools: it reads the FAT32 partition at
# a byte offset, so this needs no sudo, no loop device and no mount - which
# is what makes a boot test runnable in CI at all.
#
# Usage: extract-rpi-kernel.sh <image>
set -euo pipefail

IMG="${1:?image path required}"
case "$IMG" in
    *.xz)  xz --decompress --force --keep "$IMG"; IMG="${IMG%.xz}";;
    *.zst) zstd -d --force "$IMG"; IMG="${IMG%.zst}";;
esac

out_dir=$(dirname "$IMG")

# sfdisk -d on a plain file works unprivileged and gives a machine-readable
# layout, which beats parsing parted's prose.
p1_start=$(sfdisk -d "$IMG" 2>/dev/null |
    sed -n 's/^.*1[[:space:]]*:.*start=[[:space:]]*\([0-9][0-9]*\).*/\1/p' |
    head -n1)
[[ -n $p1_start ]] || { echo "could not parse partition 1 start"; sfdisk -d "$IMG"; exit 1; }
target="${IMG}@@$(( p1_start * 512 ))"

# The Pi 5 boots kernel_2712.img; older boards use kernel8.img, and a
# mainline build leaves Image. Take whichever is there rather than
# assuming, because linux-rpi's name for it has moved before.
kernel=""
for name in kernel_2712.img kernel8.img Image; do
    if mdir -i "$target" "::$name" >/dev/null 2>&1; then kernel="$name"; break; fi
done
[[ -n $kernel ]] || { echo "no kernel on the boot partition"; mdir -i "$target" ::; exit 1; }

# -/b lists long names one per line. Plain `mdir | awk '{print $1}'`
# gives the 8.3 short name - initramfs-linux.img comes back as
# INITRA~1, which mcopy then cannot find.
initrd=$(mdir -/b -i "$target" :: 2>/dev/null |
    sed 's#^::/##' | grep -iE '^initramfs.*\.img$' | head -n1)
[[ -n $initrd ]] || { echo "no initramfs on the boot partition"; mdir -i "$target" ::; exit 1; }

# The Pi 4 DTB first, deliberately. bcm2712 is the Pi 5 and is what a real
# board loads, but qemu-system-aarch64 -M help lists raspi0 through
# raspi4b and no raspi5 - and raspi4b is a bcm2711 machine, so a bcm2712
# device tree describes hardware it does not have and the guest exits at
# once. linux-rpi ships both; the kernel under test is the same either
# way, which is what makes taking the Pi 4 tree honest here.
dtb=""
for name in bcm2711-rpi-4-b.dtb bcm2712-rpi-5-b.dtb; do
    if mdir -i "$target" "::$name" >/dev/null 2>&1; then dtb="$name"; break; fi
done
[[ -n $dtb ]] || { echo "no usable DTB"; mdir -i "$target" :: | grep -i dtb || true; exit 1; }

mcopy -i "$target" -o "::$kernel" "$out_dir/Image"
mcopy -i "$target" -o "::${initrd}" "$out_dir/initramfs-linux.img"
mcopy -i "$target" -o "::$dtb" "$out_dir/$dtb"
echo "$dtb" > "$out_dir/dtb-name"

# The boot test must use the image's own kernel command line, not a
# hand-written guess at it - that is how root=/dev/mmcblk1p2 (which is
# manjaro-sway's Pi 4 layout, not ours) survived three runs.
mcopy -i "$target" -o "::cmdline.txt" "$out_dir/cmdline" 2>/dev/null || true

echo "extracted $kernel + $initrd + $dtb to $out_dir/"
