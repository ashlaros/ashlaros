"""What each phase does.

The ordering is the point of the orchestrator: the target's repository stack
must exist before any ashlaros-* package is fetched, and the TPM enrolment
must happen after the bootloader phase has written the initramfs and
crypttab it amends.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

from . import archinstall_adapter as arch
from .context import InstallContext
from .ui import error, info

# The target's repository stack, byte-identical in intent to iso/pacman.conf:
# pacman takes the FIRST repository carrying a package, not the highest
# version, so the v3 sections must precede core/extra or the installed system
# is a plain x86_64 one that merely has the v3 repos configured.
PACMAN_CONF = """\
#
# /etc/pacman.conf
#
# See the pacman.conf(5) manpage for option and repository directives.
#

[options]
HoldPkg     = pacman glibc
# x86_64_v3 must be listed or pacman refuses every v3 package with
# "does not have a valid architecture"
Architecture = x86_64 x86_64_v3

CheckSpace
ParallelDownloads = 8
DownloadUser = alpm

SigLevel    = Required DatabaseOptional
LocalFileSigLevel = Optional

# Repository order is load-bearing. pacman resolves a package from the first
# repository that carries it, so the v3-optimised trees come before core and
# extra; anything without a v3 build falls through to them unchanged.
[cachyos-core-v3]
Include = /etc/pacman.d/cachyos-v3-mirrorlist

[cachyos-extra-v3]
Include = /etc/pacman.d/cachyos-v3-mirrorlist

[cachyos]
Include = /etc/pacman.d/cachyos-mirrorlist

[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist

[multilib]
Include = /etc/pacman.d/mirrorlist

[ashlaros]
Include = /etc/pacman.d/ashlaros-mirrorlist
"""

CACHYOS_V3_MIRRORLIST = "Server = https://mirror.cachyos.org/repo/x86_64_v3/$repo\n"
CACHYOS_MIRRORLIST = "Server = https://mirror.cachyos.org/repo/x86_64/$repo\n"
ASHLAROS_MIRRORLIST = "Server = https://packages.ashlaros.download/$arch\n"

# Installed on the target after the base system exists. base-devel and the
# ashlaros-* set come from the archinstall config's "packages"; these are the
# desktop the ISO promises.
DESKTOP_PACKAGES = [
    "ashlaros-branding",
    "ashlaros-browser-settings",
    "firefox",
    "greetd",
    "greetd-tuigreet",
    "networkmanager",
    "bluez",
    "bluez-utils",
    "pipewire",
    "pipewire-pulse",
    "wireplumber",
    "xorg-xwayland",
    "qt5-wayland",
    "qt6-wayland",
    "gnome-keyring",
    "polkit-gnome",
    "xdg-desktop-portal-wlr",
    "xdg-user-dirs",
    "pcmanfm-qt",
    "gvfs",
    "tpm2-tools",
    # firmware updates: LVFS metadata is refreshed by a timer, but nothing
    # is ever flashed unattended - see enable_services
    "fwupd",
    # AUR helper, from the cachyos repository rather than vendored. Not an
    # optional extra: every shipped theme lists packages, and the four
    # catppuccin ones name AUR-only ones, so ashlaros-theme calls yay
    # unguarded on any machine where it is missing. Installed here rather
    # than as a depends of ashlaros-settings because that package is
    # arch=any and yay is x86_64 only - a depends would make the settings
    # uninstallable on Arch Linux ARM.
    "yay",
]


def run_command(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command, raising with its stderr attached.

    subprocess's own CalledProcessError prints the exit status and nothing
    else, which for cryptsetup and bootctl is never enough to act on.
    """
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)} exited {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def write_live_repository_stack() -> None:
    """Give the LIVE system the repositories the target will be built from.

    archinstall pacstraps with `pacstrap -C /etc/pacman.conf`, so the base
    system is resolved against the live system's configuration, not the
    target's. The ISO is built with a pacman.conf that has the CachyOS
    repositories, but that file configures the BUILD, not the running live
    system - which ships Arch's stock one. So `pacstrap ... linux-cachyos`
    failed with "target not found: linux-cachyos" and the install died at
    minimal_installation.

    Writing the same stack here fixes it at the source: one definition,
    used for the live system and copied to the target.
    """
    live = Path("/etc")
    live.joinpath("pacman.conf").write_text(PACMAN_CONF)
    pacman_d = live / "pacman.d"
    pacman_d.mkdir(parents=True, exist_ok=True)
    (pacman_d / "cachyos-v3-mirrorlist").write_text(CACHYOS_V3_MIRRORLIST)
    (pacman_d / "cachyos-mirrorlist").write_text(CACHYOS_MIRRORLIST)
    (pacman_d / "ashlaros-mirrorlist").write_text(ASHLAROS_MIRRORLIST)

    # the live ISO already trusts these keys - it installed packages from
    # both repositories at build time - so only the databases need fetching
    run_command(["pacman", "-Sy", "--noconfirm"])
    info("› live repositories configured for the target's package stack")


def prepare_live(ctx: InstallContext) -> None:
    """Load the archinstall config and check the machine can be installed to."""
    handler = arch.load_arch_config(ctx.config_path, ctx.creds_path)
    ctx.state["arch_config_handler"] = handler
    ctx.state["mirror_handler"] = arch.make_mirror_handler()

    write_live_repository_stack()

    config = handler.config
    if arch.is_systemd_boot(config) and not arch.has_uefi():
        raise RuntimeError(
            "this ISO boots systemd-boot, which needs UEFI; "
            "the machine reports a legacy BIOS boot"
        )


def install_system(ctx: InstallContext) -> None:
    """Partition, format, and pacstrap the target."""
    handler = ctx.state["arch_config_handler"]
    mirror_handler = ctx.state["mirror_handler"]
    config = handler.config

    info("› partitioning, formatting and encrypting")
    arch.perform_filesystem_operations(config)

    info("› opening the installer context")
    with arch.open_installer(config, ctx.target, silent=True) as installer:
        installer.mount_ordered_layout()
        installer.sanity_check()

        if arch.is_encrypted(config):
            installer.generate_key_files()

        if config.mirror_config:
            installer.set_mirrors(mirror_handler, config.mirror_config, on_target=False)

        info("› installing the base system")
        # kb_layout blanked: archinstall otherwise boots the target in a
        # container purely to run localectl. The keymap is written directly
        # in configure_system, which needs no such round trip.
        locale_config = (
            replace(config.locale_config, kb_layout="") if config.locale_config else None
        )
        installer.minimal_installation(
            hostname=config.hostname,
            locale_config=locale_config,
        )

        if config.mirror_config:
            installer.set_mirrors(mirror_handler, config.mirror_config, on_target=True)

        # the repository stack must be in place before any ashlaros-* or
        # cachyos package is requested from the target
        write_repository_stack(ctx)

        if config.swap and config.swap.enabled:
            installer.setup_swap(algo=config.swap.algorithm)

        info("› installing the AshlarOS package set")
        installer.add_additional_packages(config.packages)
        installer.add_additional_packages(DESKTOP_PACKAGES)

        info("› creating the user")
        users = arch.users(config)
        if users:
            installer.create_users(users)

        if config.timezone:
            installer.set_timezone(config.timezone)
        if config.ntp:
            installer.activate_time_synchronization()
        if root := arch.root_user(config):
            installer.set_user_password(root)

        installer.genfstab()

        ctx.state["installer_bootloader_done"] = install_bootloader(ctx, installer, config)


def write_repository_stack(ctx: InstallContext) -> None:
    """Give the target the same repositories the live system uses.

    Written before the keyring package exists on the target, so the CachyOS
    and AshlarOS sections are unusable until trust_keys runs - which is why
    that runs in this same phase, immediately after.
    """
    etc = ctx.target / "etc"
    (etc / "pacman.conf").write_text(PACMAN_CONF)

    pacman_d = etc / "pacman.d"
    pacman_d.mkdir(parents=True, exist_ok=True)
    (pacman_d / "cachyos-v3-mirrorlist").write_text(CACHYOS_V3_MIRRORLIST)
    (pacman_d / "cachyos-mirrorlist").write_text(CACHYOS_MIRRORLIST)
    (pacman_d / "ashlaros-mirrorlist").write_text(ASHLAROS_MIRRORLIST)

    trust_keys(ctx)


def trust_keys(ctx: InstallContext) -> None:
    """Trust the keys the target's repositories sign with, before their packages exist.

    The live system already trusts both, so its key material is what the
    target needs - but it cannot be staged under /usr/share/pacman/keyrings:
    ashlaros-keyring owns those paths and pacman refuses to install over
    files it does not own ("ashlaros.gpg exists in filesystem" failed the
    whole pacstrap transaction). The keys go into the keyring database
    instead, which no package owns, and ashlaros-keyring installs its own
    copies of the files later without conflict.
    """
    live_keyrings = Path("/usr/share/pacman/keyrings")
    # not /tmp: arch-chroot mounts a fresh tmpfs over it, so a file staged
    # there is invisible inside the chroot ("gpg: can't open ...")
    staged = ctx.target / "var/cache/ashlaros-keys"
    staged.mkdir(parents=True, exist_ok=True)

    run_command(["arch-chroot", str(ctx.target), "pacman-key", "--init"])
    run_command(["arch-chroot", str(ctx.target), "pacman-key", "--populate", "archlinux"])

    for name in ("cachyos", "ashlaros"):
        keyring = live_keyrings / f"{name}.gpg"
        if not keyring.exists():
            continue
        shutil.copy2(keyring, staged / keyring.name)
        inside = f"/var/cache/ashlaros-keys/{keyring.name}"
        run_command(["arch-chroot", str(ctx.target), "pacman-key", "--add", inside])
        # --add imports without trusting; only a local signature makes
        # pacman accept a database signed with the key
        for fingerprint in key_fingerprints(keyring):
            run_command(
                ["arch-chroot", str(ctx.target), "pacman-key", "--lsign-key", fingerprint]
            )

    shutil.rmtree(staged, ignore_errors=True)


def key_fingerprints(keyring: Path) -> list[str]:
    """Every primary-key fingerprint in a keyring file.

    Only the fpr record following a pub: subkeys emit one too, and
    pacman-key --lsign-key on a subkey fingerprint fails.
    """
    listing = subprocess.run(
        ["gpg", "--show-keys", "--with-colons", str(keyring)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    fingerprints = []
    primary = False
    for line in listing.splitlines():
        record = line.split(":")[0]
        if record == "pub":
            primary = True
        elif record == "fpr" and primary:
            fingerprints.append(line.split(":")[9])
            primary = False
        elif record == "sub":
            primary = False
    return fingerprints


def install_bootloader(ctx: InstallContext, installer, config) -> bool:
    bootloader = arch.bootloader(config)
    if bootloader is None:
        info("› no bootloader requested")
        return False

    info(f"› installing the bootloader ({bootloader.value})")
    installer.add_bootloader(bootloader)
    return True


def configure_system(ctx: InstallContext) -> None:
    """The settings archinstall does not own: the keymap, for both the
    virtual console and X11/Wayland."""
    handler = ctx.state["arch_config_handler"]
    config = handler.config

    keymap = config.locale_config.kb_layout if config.locale_config else ""
    if keymap:
        (ctx.target / "etc/vconsole.conf").write_text(f"KEYMAP={keymap}\n")
        write_x11_keymap(ctx, keymap)


def write_x11_keymap(ctx: InstallContext, keymap: str) -> None:
    """Give the desktop the keymap the user chose, not just the console.

    vconsole.conf sets the virtual console alone. The sway config asks
    localectl for the *X11 Layout* (see keyboard.sh) and that comes from
    /etc/X11/xorg.conf.d/00-keyboard.conf, which nothing else writes here -
    so a user who picked `de` got a `us` desktop while the TTY was right.

    localectl itself cannot do this: it has no --root, and running it in
    the chroot needs a dbus the target is not running. The file is small
    and its format is stable, so it is written directly.
    """
    layout, variant = x11_layout_for(keymap)

    conf = ctx.target / "etc/X11/xorg.conf.d/00-keyboard.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)
    options = [f'Option "XkbLayout" "{layout}"']
    if variant:
        options.append(f'Option "XkbVariant" "{variant}"')
    body = "\n".join(f"        {option}" for option in options)
    conf.write_text(
        "# Written by the AshlarOS installer.\n"
        "# Consumed by localectl, which the sway config reads to set the\n"
        "# desktop layout; keep it in step with /etc/vconsole.conf.\n"
        'Section "InputClass"\n'
        '        Identifier "system-keyboard"\n'
        '        MatchIsKeyboard "on"\n'
        f"{body}\n"
        "EndSection\n"
    )
    info(f"› keymap {keymap}: console and X11 layout {layout}")


# Console keymaps and X11 layouts are different namespaces: `de-latin1` is a
# keymap with no layout of that name, and `us` maps to a layout that also
# carries a model. systemd ships the mapping localectl itself uses.
KBD_MODEL_MAP = Path("/usr/share/systemd/kbd-model-map")


def x11_layout_for(keymap: str) -> tuple[str, str]:
    """(layout, variant) for a console keymap, from systemd's own table.

    An unknown keymap falls back to itself: for the common layouts the two
    names coincide, and a wrong-but-stated layout beats silently keeping
    the hardcoded `us`.
    """
    try:
        rows = KBD_MODEL_MAP.read_text().splitlines()
    except OSError:
        return keymap, ""

    for row in rows:
        if row.startswith("#") or not row.strip():
            continue
        fields = row.split()
        if len(fields) < 4 or fields[0] != keymap:
            continue
        layout, variant = fields[1], fields[3]
        return layout, "" if variant == "-" else variant
    return keymap, ""


def enroll_tpm(ctx: InstallContext) -> None:
    """Enrol the LUKS passphrase into the TPM so boots unlock without typing it.

    New work: omarchy has no TPM handling at all. PCR 7 is the secure-boot
    policy register - it is stable across kernel updates, unlike PCR 4 or 8,
    so an ordinary upgrade does not invalidate the enrolment.

    No TPM is not an error. A machine without one keeps passphrase unlock,
    which is what an unencrypted-adjacent fallback should be: the disk stays
    encrypted, only the convenience is absent.
    """
    if not ctx.encrypt:
        info("› encryption disabled; nothing to enrol")
        return

    if not tpm_available():
        info("› no TPM2 device; leaving passphrase unlock in place")
        return

    device = luks_device(ctx)
    if device is None:
        raise RuntimeError("encryption is on but no LUKS partition was found")

    passphrase = ctx.user_credentials.get("encryption_password")
    if not passphrase:
        raise RuntimeError("encryption is on but no passphrase is in user_credentials.json")

    info(f"› enrolling {device} into the TPM (PCR 7)")
    # the existing passphrase authorises adding the new keyslot; it is passed
    # on the environment rather than the command line, where /proc would
    # expose it to every process on the live system
    result = subprocess.run(
        ["systemd-cryptenroll", "--tpm2-device=auto", "--tpm2-pcrs=7", str(device)],
        capture_output=True,
        text=True,
        env={"PASSWORD": passphrase, "PATH": "/usr/bin:/bin"},
    )
    if result.returncode != 0:
        # a failed enrolment leaves the passphrase keyslot untouched, so the
        # system still boots; say so rather than failing the install
        error(
            "TPM enrolment failed; the passphrase still unlocks the disk: "
            f"{result.stderr.strip()}"
        )
        return

    add_crypttab_tpm_option(ctx, device)


def tpm_available() -> bool:
    """Whether systemd sees a usable TPM2 device.

    --tpm2-device=list prints a header row and one row per device, so an
    empty body means none.
    """
    result = subprocess.run(
        ["systemd-cryptenroll", "--tpm2-device=list"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    return bool(result.stdout.strip().splitlines()[1:])


def luks_device(ctx: InstallContext) -> Path | None:
    """The block device holding the LUKS2 container."""
    handler = ctx.state["arch_config_handler"]
    for partition in arch.encrypted_partitions(handler.config):
        dev_path = getattr(partition, "dev_path", None)
        if dev_path:
            return Path(dev_path)
    return None


def add_crypttab_tpm_option(ctx: InstallContext, device: Path) -> None:
    """Write the crypttab entry sd-encrypt unlocks root from.

    archinstall needs no crypttab: it passes cryptdevice=...:root on the
    kernel command line, which only the busybox `encrypt` hook parses.
    sd-encrypt reads /etc/crypttab.initramfs, and nothing else creates it -
    the plain /etc/crypttab that systemd ships is a comment-only stub with
    no mapping to amend, which is why an earlier version of this function
    found "no mapping" and returned before switching the hooks.

    So the file is written outright rather than edited: this installer owns
    root's mapping, and there is no prior entry to preserve.
    """
    crypttab = ctx.target / "etc/crypttab.initramfs"
    crypttab.write_text(
        "# written by the AshlarOS installer: sd-encrypt unlocks root from\n"
        "# the TPM2 keyslot enrolled against PCR 7, passphrase as fallback\n"
        f"{mapper_name(ctx)} UUID={device_uuid(device)} none tpm2-device=auto\n"
    )
    info(f"› {crypttab.name}: root unlocks via TPM, passphrase as fallback")

    use_systemd_initramfs(ctx)
    use_sd_encrypt_cmdline(ctx, device)

    # the initramfs embeds crypttab.initramfs and the hook set, so it has to
    # be rebuilt for either to take effect at boot
    run_command(["arch-chroot", str(ctx.target), "mkinitcpio", "-P"])


def mapper_name(ctx: InstallContext) -> str:
    """The device-mapper name the root volume is unlocked as.

    It has to match what the bootloader entry and fstab already reference,
    so it is read back from the running mount rather than assumed.
    """
    if Path("/dev/mapper/root").exists():
        return "root"
    for entry in sorted(Path("/dev/mapper").iterdir()):
        if entry.name != "control":
            return entry.name
    raise RuntimeError("no device-mapper node for the unlocked root volume")


def device_uuid(device: Path) -> str:
    """The LUKS container's UUID, which is what crypttab names it by."""
    return subprocess.run(
        ["blkid", "-s", "UUID", "-o", "value", str(device)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def use_sd_encrypt_cmdline(ctx: InstallContext, device: Path) -> None:
    """Rewrite the boot entry's cryptdevice= for sd-encrypt.

    archinstall writes `cryptdevice=PARTUUID=...:root`, which only the
    busybox hook parses; sd-encrypt looks for rd.luks.*. Left alone the
    initramfs would come up with the crypttab entry but no idea which
    device it names, and drop to a rescue shell.
    """
    uuid = device_uuid(device)
    entries = sorted((ctx.target / "boot/loader/entries").glob("*.conf"))
    if not entries:
        error("no loader entries to amend; the boot line still names cryptdevice=")
        return

    for entry in entries:
        rewritten = []
        for line in entry.read_text().splitlines():
            if not line.startswith("options"):
                rewritten.append(line)
                continue
            kept = [
                word
                for word in line.split()
                if not word.startswith("cryptdevice=")
            ]
            kept.insert(1, f"rd.luks.name={uuid}=root")
            rewritten.append(" ".join(kept))
        entry.write_text("\n".join(rewritten) + "\n")
    info(f"› boot entries: rd.luks.name={uuid}=root")


def use_systemd_initramfs(ctx: InstallContext) -> None:
    """Swap the busybox encrypt hook for the systemd one.

    The stock HOOKS line uses `encrypt`, which is the busybox unlocker: it
    reads neither crypttab nor a TPM2 keyslot and always prompts. Only
    `sd-encrypt`, under the `systemd` init hook, honours tpm2-device=auto -
    so without this the enrolment above succeeds and changes nothing, which
    is exactly what booting the installed system showed.

    udev/keymap/consolefont have systemd equivalents; the whole set has to
    move together, because sd-encrypt requires systemd to have run.
    """
    conf = ctx.target / "etc/mkinitcpio.conf"
    replacements = {
        "udev": "systemd",
        "keymap": "sd-vconsole",
        "encrypt": "sd-encrypt",
    }
    dropped = {"consolefont"}  # sd-vconsole covers both font and keymap

    lines = []
    for line in conf.read_text().splitlines():
        if not line.startswith("HOOKS="):
            lines.append(line)
            continue
        hooks = line[len("HOOKS=("):].rstrip(")").split()
        rewritten = [replacements.get(h, h) for h in hooks if h not in dropped]
        # base and systemd together is a mkinitcpio warning: systemd
        # replaces base's early userspace outright
        rewritten = [h for h in rewritten if h != "base"]
        lines.append(f"HOOKS=({' '.join(rewritten)})")
    conf.write_text("\n".join(lines) + "\n")
    info("› initramfs: sd-encrypt, so the TPM keyslot is actually used")


def configure_login(ctx: InstallContext) -> None:
    """greetd with tuigreet, and autologin when it was asked for."""
    greetd_dir = ctx.target / "etc/greetd"
    greetd_dir.mkdir(parents=True, exist_ok=True)

    config = [
        "[terminal]",
        "vt = 1",
        "",
        "[default_session]",
        'command = "tuigreet --time --remember --cmd sway"',
        'user = "greeter"',
    ]

    if ctx.autologin:
        config += [
            "",
            "# autologin: the disk passphrase (or its TPM enrolment) is the",
            "# authentication that matters on a single-user machine",
            "[initial_session]",
            'command = "sway"',
            f'user = "{ctx.username}"',
        ]

    (greetd_dir / "config.toml").write_text("\n".join(config) + "\n")
    run_command(["arch-chroot", str(ctx.target), "systemctl", "enable", "greetd.service"])


# fwupd.service is deliberately absent: it is Type=dbus with a D-Bus
# activation file and no [Install] section, so it cannot be enabled and
# does not need to be - it starts when something talks to it.
#
# fwupd-refresh.timer only downloads LVFS metadata. Applying an update
# stays an explicit `fwupdmgr update`: a bad capsule bricks a board, and
# there is no rollback from the OS side on hardware we do not control.
SERVICES = (
    "NetworkManager.service",
    "bluetooth.service",
    "systemd-timesyncd.service",
    "fwupd-refresh.timer",
)


def enable_services(ctx: InstallContext) -> None:
    for service in SERVICES:
        run_command(["arch-chroot", str(ctx.target), "systemctl", "enable", service])


def run_hardware_detection(ctx: InstallContext) -> None:
    """Let chwd pick the graphics driver for this machine.

    -a pci free 0300 is chwd's own "install the free driver for the display
    controller" invocation. A machine it has no profile for is not a failure:
    the kernel's built-in drivers still bring up a display.
    """
    result = subprocess.run(
        ["arch-chroot", str(ctx.target), "chwd", "-a", "pci", "free", "0300"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error(f"chwd found no profile to install: {result.stderr.strip()}")
        return
    info("› chwd installed the detected graphics profile")


def validate_boot(ctx: InstallContext) -> None:
    """Fail here rather than at the boot menu.

    A missing loader entry is the one failure mode that looks like a
    successful install right up until the machine does not boot.
    """
    esp = ctx.target / ctx.esp_mount.lstrip("/")
    entries = sorted((esp / "loader/entries").glob("*.conf"))
    if not entries:
        raise RuntimeError(f"no systemd-boot entries were written to {esp}/loader/entries")

    efi = esp / "EFI/systemd/systemd-bootx64.efi"
    if not efi.exists():
        raise RuntimeError(f"{efi} is missing; the ESP holds no bootloader")

    info(f"› {len(entries)} boot entry/entries and systemd-boot present on the ESP")
