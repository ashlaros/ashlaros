#!/usr/bin/env bash
#
# Build the Raspberry Pi 5 image.
#
# Not archiso: archiso targets x86_64 UEFI and emits an ISO to boot an
# installer from. A Pi boots board firmware off a FAT partition and has no
# installer, so what ships is a disk image already in its final state.
#
# The base is Arch Linux ARM's rpi rootfs tarball rather than a bootstrap
# from nothing: it already carries the board firmware layout and the
# vendor kernel, and rebuilding that from scratch would be reimplementing
# ALARM badly.
#
# Runs natively on an aarch64 runner. Under emulation this takes long
# enough to change what a build costs - the same reason build-wave.yml
# gives for not emulating package builds.
set -euo pipefail

readonly ROOTFS_URL="${ROOTFS_URL:-http://os.archlinuxarm.org/os/ArchLinuxARM-rpi-aarch64-latest.tar.gz}"
readonly REPO_URL="${REPO_URL:-https://packages.ashlaros.download}"
readonly KEY_URL="${KEY_URL:-https://packages.ashlaros.download/ashlaros.gpg}"

# Sized to fit a 8 GB card with room to spare; the root partition grows to
# fill whatever it is written to on first boot, so this is a floor and not
# a budget.
readonly IMAGE_MB="${IMAGE_MB:-7000}"
readonly BOOT_MB=512

usage() { echo "usage: build-image.sh <output-dir> [version]" >&2; exit 2; }

[[ $# -ge 1 ]] || usage
out_dir=$(realpath "$1")
version="${2:-$(date +%Y.%m.%d)}"
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

work=$(mktemp -d)
mount_root="$work/mnt"
loop=""

cleanup() {
    set +e
    if mountpoint -q "$mount_root/boot" 2>/dev/null; then umount "$mount_root/boot"; fi
    for d in dev/pts dev sys proc; do
        mountpoint -q "$mount_root/$d" 2>/dev/null && umount -l "$mount_root/$d"
    done
    mountpoint -q "$mount_root" 2>/dev/null && umount "$mount_root"
    [[ -n $loop ]] && losetup -d "$loop" 2>/dev/null
    rm -rf "$work"
}
trap cleanup EXIT

say() { printf '\n== %s\n' "$*" >&2; }

say "fetching the Arch Linux ARM rpi rootfs"
mkdir -p "$mount_root"
curl -fsSL "$ROOTFS_URL" -o "$work/rootfs.tar.gz"

image="$work/ashlaros-${version}-aarch64-rpi5.img"
say "creating a ${IMAGE_MB}MB image"
truncate -s "${IMAGE_MB}M" "$image"

# A Pi's firmware reads the FAT partition before any kernel exists, so the
# layout is the vendor one: FAT32 boot, ext4 root. No ESP, no systemd-boot.
parted -s "$image" mklabel msdos
parted -s "$image" mkpart primary fat32 1MiB "$((BOOT_MB + 1))MiB"
parted -s "$image" set 1 boot on
parted -s "$image" mkpart primary ext4 "$((BOOT_MB + 1))MiB" 100%

loop=$(losetup --show -fP "$image")
mkfs.vfat -F32 -n ASHLAR_BOOT "${loop}p1" >/dev/null
mkfs.ext4 -q -L ASHLAR_ROOT "${loop}p2"

mount "${loop}p2" "$mount_root"
mkdir -p "$mount_root/boot"
mount "${loop}p1" "$mount_root/boot"

say "unpacking the rootfs"
bsdtar -xpf "$work/rootfs.tar.gz" -C "$mount_root"

say "wiring the repository and keyring"
install -Dm644 "$here/pacman.conf.aarch64" "$mount_root/etc/pacman.conf"
printf 'Server = %s/$arch\n' "$REPO_URL" > "$mount_root/etc/pacman.d/ashlaros-mirrorlist"

for d in proc sys dev dev/pts; do
    mkdir -p "$mount_root/$d"
done
mount -t proc proc "$mount_root/proc"
mount -t sysfs sys "$mount_root/sys"
mount -o bind /dev "$mount_root/dev"
mount -t devpts devpts "$mount_root/dev/pts"

# resolv.conf comes from the host for the build only; first boot replaces
# it with NetworkManager's
cp /etc/resolv.conf "$mount_root/etc/resolv.conf"

curl -fsSL "$KEY_URL" -o "$work/ashlaros.gpg"
cp "$work/ashlaros.gpg" "$mount_root/tmp/ashlaros.gpg"

chroot "$mount_root" /bin/bash -euo pipefail <<'CHROOT'
pacman-key --init
pacman-key --populate archlinuxarm
pacman-key --add /tmp/ashlaros.gpg
pacman-key --lsign-key "$(gpg --show-keys --with-colons /tmp/ashlaros.gpg | awk -F: '/^fpr:/ {print $10; exit}')"
rm -f /tmp/ashlaros.gpg
pacman -Syu --noconfirm
CHROOT

say "installing the package set"
# comments and blank lines stripped here rather than in the file, so the
# list stays readable and still feeds pacman directly
mapfile -t packages < <(grep -vE '^\s*(#|$)' "$here/packages.aarch64")
chroot "$mount_root" pacman -S --noconfirm --needed "${packages[@]}"

say "configuring first boot"
install -Dm755 "$here/firstboot/ashlaros-firstboot" \
    "$mount_root/usr/local/bin/ashlaros-firstboot"
install -Dm644 "$here/firstboot/ashlaros-firstboot.service" \
    "$mount_root/etc/systemd/system/ashlaros-firstboot.service"

chroot "$mount_root" /bin/bash -euo pipefail <<'CHROOT'
systemctl enable ashlaros-firstboot.service
systemctl enable NetworkManager.service
systemctl enable greetd.service
systemctl enable bluetooth.service
systemctl enable cups.service
systemctl enable avahi-daemon.service
systemctl enable ufw.service

# ALARM ships alarm/alarm and root/root with sshd enabled - a machine on
# the network with published credentials. Both accounts go, sshd stays off
# until firstboot has made an account to reach.
userdel -r alarm 2>/dev/null || true
passwd -l root
systemctl disable sshd.service 2>/dev/null || true

# Never bake host keys into an image: every machine written from it would
# share one identity. firstboot regenerates.
rm -f /etc/ssh/ssh_host_*

# ufw writes policy and nothing else unless enabled; the installer learned
# this the hard way on x86_64 (see configure_firewall)
ufw --force default deny incoming
ufw --force default allow outgoing
ufw --force enable

echo ashlaros > /etc/hostname
CHROOT

say "writing os-release"
cat > "$mount_root/etc/os-release" <<EOF
NAME="AshlarOS"
PRETTY_NAME="AshlarOS (Raspberry Pi)"
ID=ashlaros
ID_LIKE=arch
BUILD_ID=$version
ANSI_COLOR="0;36"
HOME_URL="https://ashlaros.download"
LOGO=ashlaros
EOF

# fstab by label: the root partition is about to be repartitioned by
# firstboot, and a UUID written now would be wrong after that
cat > "$mount_root/etc/fstab" <<'EOF'
LABEL=ASHLAR_ROOT  /      ext4  defaults,noatime  0 1
LABEL=ASHLAR_BOOT  /boot  vfat  defaults          0 2
EOF

say "unmounting"
rm -f "$mount_root/etc/resolv.conf"
sync
umount "$mount_root/boot"
for d in dev/pts dev sys proc; do umount -l "$mount_root/$d"; done
umount "$mount_root"
losetup -d "$loop"
loop=""

say "compressing"
mkdir -p "$out_dir"
name="ashlaros-${version}-aarch64-rpi5.img.xz"
xz -T0 -9 -c "$image" > "$out_dir/$name"
( cd "$out_dir" && sha256sum "$name" > "SHA256SUMS.$name" )

say "built $out_dir/$name ($(stat -c%s "$out_dir/$name") bytes)"
