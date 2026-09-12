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
    "xdg-desktop-portal-gtk",
    "xdg-desktop-portal-wlr",
    "xdg-user-dirs",
    "pcmanfm-qt",
    "gvfs",
    # gvfs is only the framework; a backend is what actually mounts
    # something. Without these a phone plugged into a running desktop does
    # nothing at all and a share has no way to be reached by name, which
    # reads as "the file manager is broken" rather than as a missing
    # package. pcmanfm-qt names gvfs-mtp in its own optdepends.
    "gvfs-mtp",
    "gvfs-smb",
    "gvfs-nfs",
    "tpm2-tools",
    # Printing. cups pulls cups-filters and avahi itself, so neither is
    # listed: cups-pk-helper is what lets a desktop user add a printer
    # without root, and system-config-printer is the dialog that does it.
    "cups",
    "cups-pk-helper",
    "system-config-printer",
    # a printer on USB, which cups only reaches through libusb
    "libusb",
    # .local resolution: avahi arrives with cups, but the glibc side is a
    # separate package, and without it avahi answers on D-Bus while
    # `ping printer.local` still fails
    "nss-mdns",
    # The CLI set. We already ship grml-zsh-config, starship and both zsh
    # plugins - the decision that the shell should be pleasant is made, and
    # stopping before the tools that make it so is the inconsistency.
    # fzf and zoxide are not here: the shipped .zshrc sources them, which
    # makes them dependencies of the settings package instead.
    "ripgrep",
    "fd",
    "bat",
    "eza",
    "tldr",
    # plocate rather than mlocate: it enables its own updatedb timer
    "plocate",
    # The boot splash. In DESKTOP_PACKAGES rather than as a dependency of
    # ashlaros-branding, which is arch=any and holds assets, not machinery:
    # the theme stays installable anywhere, the mechanism lands only where
    # there is a boot to cover.
    "plymouth",
    # Runtime version manager. Installed here rather than as a dependency
    # of ashlaros-settings because that package is arch=any and installs on
    # ARM, where mise does not exist at all - neither Arch Linux ARM's
    # extra nor cachyos carries it, and Arch's own package declares
    # arch=('x86_64'), so ALARM will not inherit it later. A hard
    # dependency would make the settings package uninstallable there.
    "mise",
    # We run a third-party rolling kernel, so the window between a
    # linux-cachyos upgrade and a reboot is one a user will sit in: without
    # this the running kernel's modules are gone from disk, and plugging in
    # a USB device in that window fails with "module not found".
    "kernel-modules-hook",
    # laptop power profiles; we ship nothing that offers them today
    "power-profiles-daemon",
    # a firewall, which we had none of
    "ufw",
    # Snapshots of the root subvolume. Installed unconditionally even
    # though the layout may be ext4: the packages are small, and the
    # alternative is a machine where `ashlaros-snapshot` is missing rather
    # than one where it says snapshots are not available here.
    #
    # snap-pac is the cheap half - a pacman hook, so the snapshot exists
    # before the upgrade that broke things without anyone remembering to
    # ask for one.
    "snapper",
    "snap-pac",
    # firmware updates: LVFS metadata is refreshed by a timer, but nothing
    # is ever flashed unattended - see enable_services
    "fwupd",
    # An editor has to exist: $EDITOR is set in the shipped .profile and
    # git, visudo and systemctl edit all consume it, including from a TTY
    # or an ssh session. vim carries the desktop file the mime list points
    # at; nano is 2.7 MiB and is what someone who did not choose vim needs
    # when a commit drops them into it. The live ISO already has both.
    "vim",
    "nano",
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


def use_plymouth_initramfs(ctx: InstallContext) -> bool:
    """Put the plymouth hook in the initramfs, before whatever unlocks root.

    Order is the whole of it. The hook starts plymouthd and shows the
    splash, so it has to run before sd-encrypt asks for a passphrase - if
    it runs after, the prompt is drawn on a bare console and the splash
    appears once the disk is already open, which looks worse than no
    splash at all.

    Returns whether the file changed, so the caller can decide whether an
    initramfs rebuild is owed.
    """
    conf = ctx.target / "etc/mkinitcpio.conf"
    lines = []
    changed = False

    for line in conf.read_text().splitlines():
        if not line.startswith("HOOKS=") or "plymouth" in line:
            lines.append(line)
            continue
        hooks = line[len("HOOKS=("):].rstrip(")").split()
        # after `systemd`/`udev`, which set up the device nodes plymouth
        # draws on, and before any unlocker
        anchor = next(
            (i for i, h in enumerate(hooks) if h in ("systemd", "udev")),
            0,
        )
        hooks.insert(anchor + 1, "plymouth")
        lines.append(f"HOOKS=({' '.join(hooks)})")
        changed = True

    if changed:
        conf.write_text("\n".join(lines) + "\n")
        info("› initramfs: plymouth ahead of the unlocker")
    return changed


def add_splash_cmdline(ctx: InstallContext) -> None:
    """Ask the kernel to be quiet and the splash to come up.

    Without `splash` plymouth shows nothing, and without `quiet` the
    kernel's own messages are drawn over it - the splash is there but
    scrolled off by the time anyone looks.

    Separate from use_sd_encrypt_cmdline, which does its own rewriting and
    runs only on encrypted installs: an unencrypted machine has a boot to
    cover too, and neither path may assume the other ran.
    """
    entries = sorted((ctx.target / "boot/loader/entries").glob("*.conf"))
    if not entries:
        error("no loader entries to amend; the boot shows no splash")
        return

    for entry in entries:
        rewritten = []
        for line in entry.read_text().splitlines():
            if not line.startswith("options"):
                rewritten.append(line)
                continue
            words = line.split()
            for flag in ("quiet", "splash"):
                if flag not in words:
                    words.append(flag)
            rewritten.append(" ".join(words))
        entry.write_text("\n".join(rewritten) + "\n")
    info("› boot entries: quiet splash")


def configure_splash(ctx: InstallContext) -> None:
    """Select the theme and make sure the initramfs carries it.

    plymouth-set-default-theme -R would rebuild the initramfs itself, which
    on an encrypted install is a second rebuild racing the one
    add_crypttab_tpm_option already does. So the theme is set without -R
    and the rebuild is done once, here, after every hook edit is in place.
    """
    theme = ctx.target / "usr/share/plymouth/themes/ashlaros/ashlaros.plymouth"
    if not theme.exists():
        info("› no ashlaros plymouth theme installed, leaving the boot bare")
        return

    run_command(
        ["arch-chroot", str(ctx.target), "plymouth-set-default-theme", "ashlaros"]
    )
    use_plymouth_initramfs(ctx)
    add_splash_cmdline(ctx)
    # Unconditional: the hook edit above may be a no-op on a re-run, but
    # the theme change still has to reach the initramfs, and mkinitcpio is
    # the only thing that puts it there.
    run_command(["arch-chroot", str(ctx.target), "mkinitcpio", "-P"])
    info("› boot splash: the ashlar courses, then the name")


def configure_login(ctx: InstallContext) -> None:
    """greetd with tuigreet, and autologin when it was asked for."""
    greetd_dir = ctx.target / "etc/greetd"
    greetd_dir.mkdir(parents=True, exist_ok=True)

    # Not "sway" bare: the shipped ~/.profile holds the session's
    # environment - QT_QPA_PLATFORM, the portal theme, MOZ_ENABLE_WAYLAND,
    # EDITOR - and greetd execs its command directly, so a login shell is
    # the only thing in the chain that reads it.
    #
    # This gets those variables into sway. Getting them into the desktop
    # needs the other half: sway's autostart hands them to the systemd user
    # manager, because everything else here is a user unit and inherits the
    # manager's environment rather than sway's.
    session = "sh -lc sway"

    config = [
        "[terminal]",
        "vt = 1",
        "",
        "[default_session]",
        f'command = "tuigreet --time --remember --cmd \'{session}\'"',
        'user = "greeter"',
    ]

    if ctx.autologin:
        config += [
            "",
            "# autologin: the disk passphrase (or its TPM enrolment) is the",
            "# authentication that matters on a single-user machine",
            "[initial_session]",
            f'command = "{session}"',
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
    # printing, and the mDNS responder that finds a network printer without
    # anyone typing an address
    "cups.service",
    "avahi-daemon.service",
    # Both carry [Install] sections, so neither starts on its own -
    # power-profiles-daemon is Type=dbus but is still WantedBy graphical,
    # and the cleanup service is what removes the kept module trees.
    "power-profiles-daemon.service",
    "linux-modules-cleanup.service",
    "ufw.service",
)


def enable_services(ctx: InstallContext) -> None:
    for service in SERVICES:
        run_command(["arch-chroot", str(ctx.target), "systemctl", "enable", service])


# Snapper's own template keeps 50 numbered snapshots and creates a timeline
# one every hour forever. On a root subvolume that is a disk that fills up
# quietly, so the numbers below are the retention policy rather than a
# preference: a bounded number of snapshots around package transactions,
# and no timeline at all.
SNAPPER_ROOT_CONFIG = {
    # snap-pac brackets every pacman transaction, so updates are what
    # produce snapshots here - not the clock
    "TIMELINE_CREATE": "no",
    "TIMELINE_CLEANUP": "yes",
    "NUMBER_CLEANUP": "yes",
    "NUMBER_MIN_AGE": "1800",
    "NUMBER_LIMIT": "12",
    "NUMBER_LIMIT_IMPORTANT": "6",
    # stop making snapshots rather than fill the disk: below these the
    # cleanup runs harder, and a machine that cannot boot for lack of space
    # is worse than one missing its oldest snapshot
    "SPACE_LIMIT": "0.3",
    "FREE_LIMIT": "0.2",
}


def configure_snapshots(ctx: InstallContext) -> None:
    """Configure snapper, when the root is btrfs.

    The configurator offers ext4 as well, so this has to be a no-op there
    rather than a failure - nothing in the update path may depend on
    snapshots existing.

    create-config makes /.snapshots itself; the subvolume layout the
    configurator asks archinstall for (@ for root, @home separate) is what
    makes a root rollback leave $HOME alone.
    """
    fstype = subprocess.run(
        ["findmnt", "-no", "FSTYPE", str(ctx.target)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    if fstype != "btrfs":
        info(f"› root is {fstype or 'not btrfs'}, so snapshots are not configured")
        return

    result = subprocess.run(
        ["arch-chroot", str(ctx.target), "snapper", "--no-dbus", "-c", "root",
         "create-config", "/"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # not fatal: an installed system without snapshots still boots, and
        # ashlaros-snapshot says loudly that it has no config rather than
        # pretending a snapshot was taken
        error(f"snapper create-config failed: {result.stderr.strip()}")
        return

    config = ctx.target / "etc/snapper/configs/root"
    lines = config.read_text().splitlines()
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0]
        if key in SNAPPER_ROOT_CONFIG:
            lines[index] = f'{key}="{SNAPPER_ROOT_CONFIG[key]}"'
    config.write_text("\n".join(lines) + "\n")

    # the timeline timer is what the config just turned off; cleanup is what
    # enforces the numbers above
    run_command(
        ["arch-chroot", str(ctx.target), "systemctl", "enable", "snapper-cleanup.timer"]
    )
    info("› snapshots configured, keeping 12 around package transactions")


def configure_firewall(ctx: InstallContext) -> None:
    """Deny incoming, allow outgoing.

    A desktop listens for nothing by default, so the policy costs nothing
    and the machine stops answering whatever a hotel or conference network
    probes for. Enabling ufw.service without this leaves the defaults ufw
    ships, which is a firewall that is running and permitting everything.

    No hole for mDNS: ufw's before.rules already ACCEPTs udp to
    224.0.0.251:5353, and ufw-not-local RETURNs on MULTICAST before the
    drop, so .local resolution and printer discovery survive. Checked
    against the shipped rules rather than assumed, because a firewall that
    silently breaks printing is worse than no firewall.

    Printing itself needs no hole either: cups talks outbound to a printer,
    and only sharing a local queue would need 631 inbound.
    """
    for args in (
        ["default", "deny", "incoming"],
        ["default", "allow", "outgoing"],
    ):
        run_command(["arch-chroot", str(ctx.target), "ufw", *args])
    info("› firewall denies incoming, allows outgoing")


def configure_mdns(ctx: InstallContext) -> None:
    """Teach the resolver about .local names.

    Installing nss-mdns drops the libraries in and changes nothing: the
    `hosts:` line decides what glibc actually consults, and Arch ships it
    without mdns. So avahi answers on D-Bus while `ping printer.local`
    still fails, which looks like a broken printer rather than an unedited
    config file.

    mdns4_minimal goes before `resolve`, and carries [NOTFOUND=return] so a
    name that is not on the link falls through to DNS instead of ending the
    lookup.
    """
    nsswitch = ctx.target / "etc/nsswitch.conf"
    lines = nsswitch.read_text().splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("hosts:"):
            continue
        if "mdns" in line:
            return
        entries = line.split()
        # after `files`/`myhostname` if present, so a local override still
        # wins, and before `resolve` and `dns`, which is the point
        cut = next(
            (i for i, e in enumerate(entries) if e in ("resolve", "dns")),
            len(entries),
        )
        entries.insert(cut, "mdns4_minimal [NOTFOUND=return]")
        lines[index] = " ".join(entries)
        nsswitch.write_text("\n".join(lines) + "\n")
        info("› .local names resolve over mdns")
        return
    error("no hosts: line in nsswitch.conf - .local names will not resolve")


def run_hardware_detection(ctx: InstallContext) -> None:
    """Let chwd pick the graphics driver for this machine.

    0300 is the PCI class for a display controller; -a takes it as its one
    optional argument. chwd used to spell this "-a pci free 0300", which
    1.24 rejects outright - "unexpected argument 'free' found" - so every
    install was silently getting no driver profile at all. A machine chwd
    has no profile for is still not a failure: the kernel's built-in
    drivers bring up a display.
    """
    result = subprocess.run(
        ["arch-chroot", str(ctx.target), "chwd", "-a", "0300"],
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
