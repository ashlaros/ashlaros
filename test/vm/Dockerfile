# The VM harness: QEMU with UEFI firmware and a software TPM, plus python
# for the QMP client, and iasl to build the optional ACPI lid.
#
# A container rather than host packages, because the host is not
# necessarily Arch and the firmware paths differ everywhere else.
FROM archlinux:base

RUN pacman -Sy --noconfirm --needed \
      qemu-system-x86 qemu-img edk2-ovmf swtpm python acpica \
    && pacman -Scc --noconfirm
