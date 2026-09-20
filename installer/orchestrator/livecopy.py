"""Seed the target from the live medium instead of unpacking it again.

The ISO already carries a working AshlarOS userland: 505 of the packages
an install needs are unpacked and configured on the medium. Pacstrapping
them onto the target means shipping every one of them twice - once
unpacked in the squashfs, once as a .pkg.tar.zst in the cache so the
install can find it offline. Measured on the 2026.09.19 ISO that second
copy is 1256 MiB, 37% of the image, and every user downloads it.

So the target is seeded by copying the medium's own root, and pacstrap is
left with only what the medium lacks - 190 packages, 218 MiB. That is
what most live installers do; Calamares calls it unpackfs.

Two things make this safe rather than clever:

  - The cache is a strict superset of the live root. Checked against the
    published ISO: 0 packages are installed on the medium that the target
    does not also want, so the copy never has to subtract a package, only
    add.
  - A copied root is a real pacman system. Its database comes with it, so
    `pacman -Qk` reports no missing files and further packages install on
    top normally.

What the copy must NOT bring is the configuration that makes a medium a
live medium - see LIVE_ONLY.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .context import InstallContext
from .ui import info

# Where the initramfs mounts the read-only squashfs. The running root is an
# overlay on top of it, so `/` carries this session's writes - the
# configurator's JSON under /root, the install log, the state file - and
# the mount underneath is the pristine image. Copying `/` would put the
# session on the installed system.
LIVE_ROOT = Path("/run/archiso/airootfs")

# Everything under iso/airootfs/ in the repository, which is exactly the
# set of files that exist to make this medium a live medium.
#
# Derived from the profile at build time rather than written out here: a
# second copy of this list is one that drifts the first time somebody adds
# a file to the profile, and the drift is silent and dangerous. The most
# important entry is /etc/shadow, which on the ISO gives root an empty
# password - copying it would install a machine anyone can log into.
LIVE_ONLY_MANIFEST = Path("/usr/share/ashlaros-installer/live-only")

# Directories that are the session rather than the system. Present in the
# squashfs as empty mount points, but listed so a future change to what the
# medium carries cannot quietly seed them.
VOLATILE = ("proc", "sys", "dev", "run", "tmp", "mnt")


def live_only_paths() -> list[str]:
    """The medium's own configuration, relative to the root.

    Empty when the manifest is missing, which is the safe direction only
    because seed_target refuses to copy without it: an unfiltered copy is
    a passwordless root, not a degraded install.
    """
    try:
        lines = LIVE_ONLY_MANIFEST.read_text().splitlines()
    except OSError:
        return []
    return [line.strip().lstrip("/") for line in lines if line.strip()]


def available() -> bool:
    """Whether the medium can seed a target at all."""
    return LIVE_ROOT.is_dir() and bool(live_only_paths())


def seed_target(ctx: InstallContext) -> bool:
    """Copy the medium's root onto the target, minus what is live-only.

    Returns whether the target was seeded. False means the caller should
    pacstrap the whole set as before, which is a slower install and not a
    broken one.
    """
    if not available():
        info("› no live root to copy from; installing the whole set")
        return False

    excludes = [*live_only_paths(), *VOLATILE]

    # rsync rather than cp: it takes an exclude list, preserves hardlinks
    # across the whole tree rather than per-file, and reports what it did.
    # --one-file-system so a bind mount under the live root cannot be
    # descended into.
    command = [
        "rsync",
        "--archive",
        "--hard-links",
        "--acls",
        "--xattrs",
        "--one-file-system",
        "--info=stats2",
    ]
    command += [f"--exclude=/{path}" for path in excludes]
    command += [f"{LIVE_ROOT}/", str(ctx.target)]

    info(f"› copying the system from the medium, less {len(excludes)} live-only paths")
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"copying the live root failed: {result.stderr.strip() or result.stdout.strip()}"
        )

    verify_not_live(ctx)
    restore_kernels(ctx)
    return True


def restore_kernels(ctx: InstallContext) -> None:
    """Do for the target what the kernel's alpm hook does on a real install.

    Copying the medium skips two things that no package owns, because both
    are produced by `/usr/share/libalpm/scripts/mkinitcpio install` when a
    kernel is unpacked - and nothing unpacks a kernel here:

      * /etc/mkinitcpio.d/<pkgbase>.preset. `pacman -Qo` reports no owner.
        Without it the install dies at `mkinitcpio -P` with "No presets
        found in /etc/mkinitcpio.d", after the disk is already written.
      * /boot/vmlinuz-<pkgbase>. mkarchiso empties /boot before packing the
        squashfs, so the copied root has no kernel image at all - only
        usr/lib/modules/<kver>/vmlinuz, which is where the hook reads from.

    The medium's own presets are no substitute: they name PRESETS=('archiso')
    and an archiso config, which is why live_only excludes them. mkinitcpio
    ships the template the hook fills in, so that is what is used here
    rather than a second copy of the same text.
    """
    template = ctx.target / "usr/share/mkinitcpio/hook.preset"
    presets = ctx.target / "etc/mkinitcpio.d"
    presets.mkdir(parents=True, exist_ok=True)
    (ctx.target / "boot").mkdir(parents=True, exist_ok=True)

    restored = []
    for marker in sorted((ctx.target / "usr/lib/modules").glob("*/pkgbase")):
        pkgbase = marker.read_text().strip()
        image = marker.parent / "vmlinuz"
        if not pkgbase or not image.exists():
            continue
        (presets / f"{pkgbase}.preset").write_text(
            template.read_text().replace("%PKGBASE%", pkgbase)
        )
        shutil.copy2(image, ctx.target / "boot" / f"vmlinuz-{pkgbase}")
        restored.append(pkgbase)

    if not restored:
        raise RuntimeError(
            "the copied root carries no kernel under usr/lib/modules, so no "
            "initramfs could be built and the target would not boot"
        )
    info(f"› kernel and preset restored for {', '.join(restored)}")


def verify_not_live(ctx: InstallContext) -> None:
    """Refuse to continue if the copy left the medium's own credentials.

    The check is cheap and the failure it guards against is the worst this
    module can produce: /etc/shadow on the ISO gives root an empty
    password, and an autologin drop-in would log that root in. An install
    that stops here is recoverable; one that boots to a passwordless
    machine is not.
    """
    shadow = ctx.target / "etc/shadow"
    if shadow.exists():
        for line in shadow.read_text().splitlines():
            fields = line.split(":")
            if fields[0] == "root" and fields[1] == "":
                raise RuntimeError(
                    "the copied root still carries the medium's empty root password"
                )

    for drop_in in ("getty@tty1.service.d", "getty@tty2.service.d"):
        if (ctx.target / "etc/systemd/system" / drop_in / "autologin.conf").exists():
            raise RuntimeError(f"the copied root still carries the medium's {drop_in}")
