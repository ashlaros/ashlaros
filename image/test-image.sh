#!/usr/bin/env bash
#
# Boot the built image under QEMU with the real Pi kernel and watch the
# serial console until userspace says it is up.
#
# The approach is manjaro-sway's (`ci/boot-smoke.sh`, `extract-rpi-kernel.sh`),
# which had already solved the two things that make this hard:
#
#   - mtools reads the FAT boot partition at a byte offset, so the kernel,
#     initramfs and DTB come out with no sudo and no loop device;
#   - `-M raspi4b` boots that kernel, so this exercises linux-rpi rather
#     than a generic one. QEMU has no raspi5 machine, so a Pi 5 image is
#     booted on the Pi 4 model - close enough to prove the kernel and the
#     root filesystem, not close enough to prove the Pi 5 firmware.
#
# So a green run here is a real boot and still not a substitute for a
# board. Publishing stays a separate manual decision.
set -euo pipefail

[[ $# -ge 1 ]] || { echo "usage: test-image.sh <image-dir> [timeout]" >&2; exit 2; }
out_dir=$(realpath "$1")
timeout_s="${2:-420}"

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
work=$(mktemp -d)
qemu_pid=""
cleanup() {
    set +e
    [[ -n $qemu_pid ]] && kill "$qemu_pid" 2>/dev/null
    rm -rf "$work"
}
trap cleanup EXIT

say() { printf '\n== %s\n' "$*" >&2; }

compressed=$(find "$out_dir" -name '*.img.xz' | head -1)
[[ -n $compressed ]] || { echo "no image in $out_dir" >&2; exit 1; }

say "extracting the kernel from the boot partition"
"$here/extract-rpi-kernel.sh" "$compressed"
image="${compressed%.xz}"
dtb=$(cat "$out_dir/dtb-name")

# QEMU's SD model insists on a power-of-two size and says so plainly:
#   Invalid SD card size: 6.84 GiB / has to be a power of 2
# The published image stays 7000 MB - padding it to 8 GiB would cost every
# downloader the difference - so the copy under test is grown instead.
# Sparse, so this costs no real disk.
qemu-img resize -f raw "$image" 8G >/dev/null

serial="$work/serial.log"
: > "$serial"

# What "it booted" means, in the order they are most reliable. systemd stops
# writing to the kernel ring buffer once journald is up, so its later
# "Reached target" lines never reach the serial - audit keeps flowing
# through kauditd, which is why manjaro-sway leads with it.
marker="${BOOT_MARKER_REGEX:-audit.*hostname=ashlaros|ashlaros[-a-z]* *login:|Ready\. Starting the desktop|Username:}"

say "booting under -M raspi4b (timeout ${timeout_s}s)"
qemu-system-aarch64 \
    -M raspi4b -m 2G -smp 4 \
    -kernel "$out_dir/Image" \
    -initrd "$out_dir/initramfs-linux.img" \
    -dtb "$out_dir/$dtb" \
    -append "root=/dev/mmcblk1p2 rw rootwait earlycon=pl011,0xfe201000 console=ttyAMA0,115200 ignore_loglevel systemd.journald.forward_to_console=1" \
    -drive file="$image",if=sd,format=raw \
    -nographic \
    -serial "file:$serial" \
    -monitor none >"$work/qemu.out" 2>&1 &
qemu_pid=$!

# QEMU exiting at once means it refused the arguments, and the message is
# in its stdout rather than on the serial console - swallowing it cost a
# 16-minute run to learn "exit code 1".
sleep 2
if ! kill -0 "$qemu_pid" 2>/dev/null; then
    echo "qemu exited immediately:" >&2
    cat "$work/qemu.out" >&2
    exit 1
fi

booted=0
for _ in $(seq 1 "$timeout_s"); do
    sleep 1
    if grep -qE "$marker" "$serial" 2>/dev/null; then booted=1; break; fi
    kill -0 "$qemu_pid" 2>/dev/null || break
done

kill "$qemu_pid" 2>/dev/null; qemu_pid=""

say "serial tail"
tail -40 "$serial" | sed 's/^/  /'

if [[ $booted -ne 1 ]]; then
    echo "no boot marker in ${timeout_s}s" >&2
    exit 1
fi

say "booted: matched the marker on the serial console"
# The first-boot script asks for a username before the network comes up,
# so reaching that prompt means systemd, the root filesystem and our own
# unit all did their jobs.
grep -qE "Username:|Ready\. Starting the desktop" "$serial" &&
    echo "  reached the firstboot prompt"
