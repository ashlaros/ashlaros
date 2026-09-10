"""Thin compatibility wall around the archinstall Python library.

ONLY this module imports from archinstall. Everything else uses these
helpers, so an archinstall API change has one place to land.

Tested against archinstall 4.4.

The canonical call sequence, mirrored from archinstall.scripts.guided:

    FilesystemHandler(disk_config).perform_filesystem_operations()
    with Installer(mountpoint, disk_config, kernels=, silent=) as inst:
        inst.mount_ordered_layout()
        inst.sanity_check()
        inst.generate_key_files()                     # encrypted only
        inst.set_mirrors(handler, mirror_config, on_target=False)
        inst.minimal_installation(...)                # base + kernel pacstrap
        inst.set_mirrors(handler, mirror_config, on_target=True)
        inst.setup_swap(algo=...)
        inst.add_bootloader(bootloader)
        inst.create_users(users)
        inst.add_additional_packages(packages)
        inst.set_timezone(tz)
        inst.activate_time_synchronization()
        inst.set_user_password(root_user)
        inst.genfstab()

Structure and approach are taken from omacom/omarchy-iso's adapter (MIT).
"""

from __future__ import annotations

import inspect
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Imports are top-level so a missing or incompatible archinstall surfaces at
# orchestrator startup, not deep inside a phase.
from archinstall.lib.args import ArchConfig, ArchConfigHandler
from archinstall.lib.disk.filesystem import FilesystemHandler
from archinstall.lib.disk.utils import get_parent_device_path, udev_sync
from archinstall.lib.hardware import SysInfo
from archinstall.lib.installer import Installer
from archinstall.lib.mirror.mirror_handler import MirrorListHandler
from archinstall.lib.models import Bootloader
from archinstall.lib.models.device import DiskLayoutType, EncryptionType
from archinstall.lib.models.users import User

from .ui import info


def load_arch_config(config_path: Path, creds_path: Path) -> ArchConfigHandler:
    """Build an ArchConfigHandler from on-disk JSON.

    ArchConfigHandler reads --config / --creds off sys.argv via argparse at
    construction time and consults no environment variable for them. Our
    wrapper strips its own flags before exec'ing python, so hand archinstall
    a synthetic argv just for this call.
    """
    import sys

    saved_argv = sys.argv
    sys.argv = [
        saved_argv[0] if saved_argv else "ashlaros-install",
        "--config", str(config_path),
        "--creds", str(creds_path),
    ]
    try:
        return ArchConfigHandler()
    finally:
        sys.argv = saved_argv


def make_mirror_handler() -> MirrorListHandler:
    # not offline: our repository stack is fetched over the network, so the
    # ISO carries no offline mirror to point at
    return MirrorListHandler(offline=False, verbose=False)


def method_accepts(method, name: str) -> bool:
    """Whether a bound archinstall method takes a named argument.

    archinstall drops parameters between releases; passing one it no longer
    accepts is a TypeError deep inside a phase.
    """
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        return False
    return name in signature.parameters


def perform_filesystem_operations(arch_config: ArchConfig) -> None:
    """Partition, format, encrypt.

    parted's partition-table commit races udev: the wipe and the first BLKPG
    registration trigger probes that hold the disk open, and the kernel then
    refuses the remaining partitions ("have been written, but we have been
    unable to inform the kernel"). The table is correct when that happens -
    only the kernel's view is stale - so settle udev and redo. The
    wipe/partition/format sequence is idempotent.
    """
    if not arch_config.disk_config:
        raise RuntimeError("disk_config missing from arch config")

    handler = FilesystemHandler(arch_config.disk_config)

    # archinstall's own TUI counts down before wiping a disk. Ours already
    # asked; in an orchestrated run that countdown renders nowhere and only
    # sleeps. Newer releases dropped the parameter, so only pass it when
    # the running version still takes it.
    kwargs = (
        {"show_countdown": False}
        if method_accepts(handler.perform_filesystem_operations, "show_countdown")
        else {}
    )

    attempts = 3
    for attempt in range(1, attempts + 1):
        udev_sync()
        try:
            handler.perform_filesystem_operations(**kwargs)
            return
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts or "unable to inform the kernel" not in str(exc):
                raise
            info(f"› partition commit lost a udev race ({attempt}/{attempts}); retrying")


@contextmanager
def open_installer(
    arch_config: ArchConfig,
    mountpoint: Path,
    silent: bool = True,
) -> Iterator[Installer]:
    """Yield an open Installer, ensuring __exit__ runs even on exception so
    the target is left unmounted for a retry."""
    if not arch_config.disk_config:
        raise RuntimeError("disk_config missing from arch config")
    with Installer(
        mountpoint,
        arch_config.disk_config,
        kernels=arch_config.kernels,
        silent=silent,
    ) as installer:
        yield installer


def is_encrypted(arch_config: ArchConfig) -> bool:
    disk = arch_config.disk_config
    if not disk or not disk.disk_encryption:
        return False
    return disk.disk_encryption.encryption_type != EncryptionType.NO_ENCRYPTION


def is_pre_mount(arch_config: ArchConfig) -> bool:
    disk = arch_config.disk_config
    return bool(disk and disk.config_type == DiskLayoutType.Pre_mount)


def bootloader(arch_config: ArchConfig) -> Bootloader | None:
    config = arch_config.bootloader_config
    if not config or config.bootloader == Bootloader.NO_BOOTLOADER:
        return None
    return config.bootloader


def is_systemd_boot(arch_config: ArchConfig) -> bool:
    return bootloader(arch_config) == Bootloader.Systemd


def has_uefi() -> bool:
    return SysInfo.has_uefi()


def parent_device_path(dev_path: Path) -> Path:
    return get_parent_device_path(dev_path)


def encrypted_partitions(arch_config: ArchConfig) -> list:
    """The device modifications' partitions selected for LUKS.

    systemd-cryptenroll needs the block device, and only the disk config
    knows which partition the encryption applies to.
    """
    disk = arch_config.disk_config
    if not disk or not disk.disk_encryption:
        return []
    return list(disk.disk_encryption.partitions or [])


def root_user(arch_config: ArchConfig) -> User | None:
    auth = arch_config.auth_config
    if not auth or not auth.root_enc_password:
        return None
    return User("root", auth.root_enc_password, False)


def users(arch_config: ArchConfig) -> list[User]:
    auth = arch_config.auth_config
    return list(auth.users) if auth and auth.users else []
