# The VM harness: QEMU with UEFI firmware and a software TPM, plus python
# for the QMP client, and iasl to build the optional ACPI lid.
#
# A container rather than host packages, because the host is not
# necessarily Arch and the firmware paths differ everywhere else.
FROM archlinux:base

# Arch splits the display devices out of qemu-system-x86, so a stock
# install has only the legacy `std` VGA. virtio-gpu is what Gnome Boxes
# and virt-manager give a guest by default, and it needs a different
# kernel driver - so testing only `std` tests only one of the two paths
# a user actually boots on.
RUN pacman -Sy --noconfirm --needed \
      qemu-system-x86 qemu-img edk2-ovmf swtpm python acpica \
      qemu-hw-display-virtio-vga qemu-hw-display-virtio-gpu \
    && pacman -Scc --noconfirm
