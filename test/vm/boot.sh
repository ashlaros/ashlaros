#!/usr/bin/env bash
# Boot an AshlarOS ISO, or the disk it installed to, under QEMU.
#
# UEFI because the profile only builds uefi.systemd-boot, and a software
# TPM because the installer enrols the LUKS passphrase into one. QMP is
# the control channel: the loader entry carries no console=ttyS0, so the
# kernel and the gum TUI draw only on the framebuffer and the serial port
# sees almost nothing.
#
#   $1     seconds before qemu is killed (default 180)
#   TPM    no  - run without a TPM, for the passphrase-only path
#   CDROM  no  - boot the installed disk instead of the installer
set -u

seconds="${1:-180}"
tpm="${TPM:-yes}"
cdrom="${CDROM:-yes}"

mkdir -p /vm/tpm /vm/out
[ -f /vm/target.qcow2 ] || qemu-img create -f qcow2 /vm/target.qcow2 20G >/dev/null

# OVMF vars must be writable and must persist across the install/reboot
# pair, or the firmware forgets the boot entry the installer wrote
[ -f /vm/ovmf_vars.fd ] || cp /usr/share/edk2/x64/OVMF_VARS.4m.fd /vm/ovmf_vars.fd

args=(
  # -cpu max: the ISO is x86_64_v3, so the guest needs AVX2. KVM is not
  # available inside this container even with /dev/kvm mapped, so this is
  # TCG - correct, and slow enough that an install takes ~35 minutes.
  -cpu max
  -m 4G
  -smp 2
  -drive "if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd"
  -drive "if=pflash,format=raw,file=/vm/ovmf_vars.fd"
)

if [[ $cdrom == yes ]]; then
  args+=(-drive "file=/vm/ashlaros.iso,media=cdrom,readonly=on" -boot order=d)
fi

args+=(
  -drive "file=/vm/target.qcow2,if=virtio,format=qcow2"
  -serial "file:/vm/out/serial.log"
  -display none
  -vga std
  -qmp "unix:/vm/qmp.sock,server=on,wait=off"
  -monitor none
)

if [[ $tpm == yes ]]; then
  # the commas here are qemu's own option syntax, not array separators
  # shellcheck disable=SC2054
  swtpm socket --tpmstate dir=/vm/tpm --ctrl type=unixio,path=/vm/tpm/sock \
    --tpm2 --daemon
  sleep 1
  # shellcheck disable=SC2054
  args+=(
    -chardev socket,id=chrtpm,path=/vm/tpm/sock
    -tpmdev emulator,id=tpm0,chardev=chrtpm
    -device tpm-tis,tpmdev=tpm0
  )
  echo "## TPM attached"
else
  echo "## no TPM"
fi

echo "## booting for ${seconds}s"
timeout "$seconds" qemu-system-x86_64 "${args[@]}"
echo "## qemu exited $?"
