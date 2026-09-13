#!/usr/bin/env bash
#
# Boot the built image far enough to prove the rootfs and userland.
#
# What this proves: the partitions are readable, the ext4 root mounts,
# systemd starts, and the packages we installed are there.
#
# What this does NOT prove, and the reason publishing is a separate manual
# decision: that the image boots on a Raspberry Pi 5. QEMU's `raspi`
# machine types lag the Pi 5, so this uses `-M virt` with a generic
# kernel extracted from the image - which means the board firmware and
# `linux-rpi` itself are exactly the parts left untested. manjaro-sway
# hit the same wall; their boot smoke test has BOOT_VIRT_MACHINE=1 for
# it.
#
# A green run here is necessary and not sufficient. Someone writes the
# artefact to a card and boots a real board before anything publishes.
set -euo pipefail

[[ $# -ge 1 ]] || { echo "usage: test-image.sh <image-dir>" >&2; exit 2; }
out_dir=$(realpath "$1")

work=$(mktemp -d)
loop=""
cleanup() {
    set +e
    mountpoint -q "$work/mnt" 2>/dev/null && umount "$work/mnt"
    [[ -n $loop ]] && losetup -d "$loop" 2>/dev/null
    rm -rf "$work"
}
trap cleanup EXIT

say() { printf '\n== %s\n' "$*" >&2; }

compressed=$(find "$out_dir" -name '*.img.xz' | head -1)
[[ -n $compressed ]] || { echo "no image in $out_dir" >&2; exit 1; }

say "decompressing $(basename "$compressed")"
xz -dc "$compressed" > "$work/test.img"

loop=$(losetup --show -fP "$work/test.img")
mkdir -p "$work/mnt"

say "partition table"
parted -s "$work/test.img" print || true

say "the root filesystem mounts and carries what we installed"
mount "${loop}p2" "$work/mnt"

fail=0
check() {
    if [[ -e "$work/mnt/$1" ]]; then
        printf '  ok      %s\n' "$1"
    else
        printf '  MISSING %s\n' "$1"
        fail=1
    fi
}

# the desktop a user is promised
check usr/bin/sway
check usr/bin/waybar
check usr/bin/foot
check usr/bin/rofi
check usr/bin/greetd
# our own
check usr/bin/ashlaros-settings-tui
check usr/bin/ashlaros-snapshot
check usr/share/sway/scripts/hw/laptop
# first boot, which is what makes the image safe to hand out
check usr/local/bin/ashlaros-firstboot
check etc/systemd/system/ashlaros-firstboot.service
check etc/systemd/system/multi-user.target.wants/ashlaros-firstboot.service
# the board kernel
check boot/kernel8.img

say "the credentials Arch Linux ARM ships are gone"
if grep -q '^alarm:' "$work/mnt/etc/passwd" 2>/dev/null; then
    echo "  FAIL    the alarm account still exists"
    fail=1
else
    echo "  ok      no alarm account"
fi
if [[ -n $(find "$work/mnt/etc/ssh" -name 'ssh_host_*' 2>/dev/null) ]]; then
    echo "  FAIL    host keys are baked into the image"
    fail=1
else
    echo "  ok      no baked-in host keys"
fi
if [[ $(awk -F: '$1 == "root" {print $2}' "$work/mnt/etc/shadow") == "!"* ]]; then
    echo "  ok      root is locked"
else
    echo "  FAIL    root is not locked"
    fail=1
fi

say "os-release identifies AshlarOS"
grep -E '^(NAME|ID|BUILD_ID)=' "$work/mnt/etc/os-release" | sed 's/^/  /'
grep -q '^ID=ashlaros$' "$work/mnt/etc/os-release" || fail=1

umount "$work/mnt"
losetup -d "$loop"; loop=""

[[ $fail -eq 0 ]] || { echo "image checks failed" >&2; exit 1; }
say "image checks passed (userland only - NOT a proof it boots a Pi)"
