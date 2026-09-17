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
# Where the ISO keeps the packages it already carries.
#
# Not /var/cache/pacman/pkg: mkarchiso's _cleanup_pacstrap_dir deletes every
# file under exactly that path before it packs the squashfs, which is why
# the published ISO ships an empty one - checked, 0 files. A cache at any
# other path survives, so the build stages one here.
ISO_PACKAGE_CACHES = (Path("/var/cache/ashlaros/pkg"),)

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
ASHLAROS_MIRRORLIST = "Server = https://ashlaros.download/packages/$arch\n"

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
    # External monitor brightness. brightnessctl only drives
    # /sys/class/backlight, which exists on a laptop panel and nowhere
    # else - so on a desktop the brightness keys, the waybar slider and
    # the idle dimming in idle.yaml all ran against nothing. ddcutil
    # speaks DDC/CI over the monitor's i2c line, and wluma already
    # discovers external monitors that way and falls back to raw DDC when
    # ddcutil-service (AUR only) is absent.
    #
    # It needs no configuration: the package ships modules-load.d for
    # i2c-dev and a udev rule tagging display i2c devices uaccess, so the
    # logged-in user reaches them without a group or a sudo rule.
    "ddcutil",
    # The kernel side of the same problem. ddcci-backlight registers a
    # /sys/class/backlight device for every monitor that answers DDC, which
    # is the interface brightnessctl, the waybar module and idle.yaml
    # already speak - so idle dimming, which has no DDC path at all, starts
    # working on a desktop (#65). ddcutil stays: the module binds to some
    # monitors and not others, and ddcutil is both the fallback in
    # brightness.sh and the tool that says what a monitor supports.
    "ddcci-driver-linux-dkms",
    # DKMS and the headers it builds against, together and always. Arch's
    # dkms ships alpm hooks that rebuild every registered module when
    # usr/lib/modules/*/build/include/ changes - which IS the headers
    # package - so a kernel installed without its headers builds no module,
    # attempts no rebuild, and reports no error at all.
    "dkms",
    "linux-cachyos-headers",
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
    # An AppImage is a self-mounting SquashFS, so without FUSE it exits
    # with a confusing error instead of running - the single most common
    # "AppImages do not work on this distro" complaint, for 1 MB.
    #
    # Both, deliberately: fuse2 is deprecated upstream but is what Type 2
    # AppImages link, and those are still the majority. Shipping only
    # fuse3 looks like it works until someone downloads an older one.
    "fuse2",
    "fuse3",
    # checkupdates.sh already counts flatpak updates and the badge tooltip
    # already claims it does. Without this the branch is dead on every
    # machine and the tooltip is a lie - the same rot as #7, except the
    # command -v guard makes it silent rather than broken.
    "flatpak",
    # Installed everywhere, enabled nowhere. A laptop with a supported
    # reader otherwise has working hardware and no way to reach it, while
    # a machine without one is unaffected: fprintd.service is D-Bus
    # activated, so it needs no SERVICES entry for the same reason fwupd
    # does not, and nothing authenticates against it until someone
    # enrols a finger in the settings TUI and asks for it.
    "fprintd",
    # What makes GNOME Boxes and virt-manager recognise an AshlarOS ISO
    # (#85). Published upstream too, but an entry in osinfo-db reaches a
    # host at its next osinfo-db release; this reaches an AshlarOS host
    # now, which is the machine most likely to be building a VM of us.
    # Inert without libosinfo, so it costs a 3 KiB file on a desktop that
    # never virtualises anything.
    "ashlaros-osinfo",
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


def live_pacman_conf() -> str:
    """PACMAN_CONF with the ISO's own package cache added as a CacheDir.

    Only the live system's copy. Pacman falls through to the mirrors on a
    miss, so this is a shortcut rather than a source of truth, and a cache
    older than the repositories loses to them on version comparison.

    The ISO's own cache is listed first and pacman's default second, so
    anything fetched during this session is reused too.
    """
    caches = [path for path in ISO_PACKAGE_CACHES if path.is_dir()]
    if not caches:
        return PACMAN_CONF
    listed = " ".join(str(path) for path in caches)
    added = (
        "[options]\n"
        "# the ISO's own packages, so an install does not fetch them again\n"
        f"CacheDir = {listed} /var/cache/pacman/pkg\n"
    )
    return PACMAN_CONF.replace("[options]\n", added, 1)


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

    The live copy gains a CacheDir the target's does not. pacstrap resolves
    against this file, so a package already on the ISO is copied from disk
    instead of fetched again - seven of them are, firefox among them at
    88 MB. The target keeps pacman's default cache, because /run/archiso
    does not exist once the machine reboots.
    """
    live = Path("/etc")
    live.joinpath("pacman.conf").write_text(live_pacman_conf())
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
    """Enrol the LUKS passphrase into the TPM, when that is what was asked for.

    New work: omarchy has no TPM handling at all. PCR 7 is the secure-boot
    policy register - it is stable across kernel updates, unlike PCR 4 or 8,
    so an ordinary upgrade does not invalidate the enrolment.

    This used to enrol whenever a TPM was present, which let hardware
    detection decide a security tradeoff on the user's behalf and left the
    machine unlocking silently forever (#64). The configurator asks now, and
    this obeys the answer; the settings TUI changes it later.

    No TPM is not an error. A machine without one keeps passphrase unlock,
    which is what an unencrypted-adjacent fallback should be: the disk stays
    encrypted, only the convenience is absent.
    """
    if not ctx.encrypt:
        info("› encryption disabled; nothing to enrol")
        return

    if ctx.tpm_unlock == "none":
        info("› passphrase unlock chosen; not enrolling the TPM")
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

    with_pin = ctx.tpm_unlock == "pin"
    info(f"› enrolling {device} into the TPM (PCR 7{', with a PIN' if with_pin else ''})")

    command = ["systemd-cryptenroll", "--tpm2-device=auto", "--tpm2-pcrs=7"]
    # the existing passphrase authorises adding the new keyslot; both it and
    # the PIN travel on the environment rather than the command line, where
    # /proc would expose them to every process on the live system
    env = {"PASSWORD": passphrase, "PATH": "/usr/bin:/bin"}
    if with_pin:
        pin = ctx.user_credentials.get("tpm_pin")
        if not pin:
            raise RuntimeError("TPM+PIN was chosen but no tpm_pin is in user_credentials.json")
        command.append("--tpm2-with-pin=yes")
        # systemd reads the new PIN from NEWPIN, which is why this can run
        # unattended at all - there is no terminal to prompt on here
        env["NEWPIN"] = pin
    command.append(str(device))

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        env=env,
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

    `autodetect` goes too, and that one is not cosmetic. It prunes the
    initramfs to the modules the machine running mkinitcpio is using - and
    mkinitcpio runs under arch-chroot on the live ISO, so the pruning is
    against the INSTALLER's hardware, not the target's. Measured on a real
    install: the initramfs carried exactly one DRM driver, bochs.ko, which
    is what the ISO's own -vga std adapter uses. A machine that boots on
    anything else (virtio_gpu under Gnome Boxes, i915, amdgpu) gets an
    initramfs with no driver for its display, and early KMS has nothing to
    bring up - which is a black screen with quiet+splash on.

    The cost is a larger initramfs, since every module ships rather than
    the detected subset. That is the right trade for an image built on one
    machine and booted on another.
    """
    conf = ctx.target / "etc/mkinitcpio.conf"
    replacements = {
        "udev": "systemd",
        "keymap": "sd-vconsole",
        "encrypt": "sd-encrypt",
    }
    # sd-vconsole covers both font and keymap; autodetect is wrong here
    # because this runs on the installer's hardware, not the target's
    dropped = {"consolefont", "autodetect"}

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


UNLOCK_HOOKS = ("encrypt", "sd-encrypt")


def use_plymouth_initramfs(ctx: InstallContext) -> bool:
    """Put the plymouth hook after kms and before whatever unlocks root.

    Both halves are load-bearing, and an earlier version implemented only
    the second - it anchored on systemd/udev and never looked at kms.

    AFTER kms, because plymouth draws through KMS: with no DRM driver
    loaded and no EFI framebuffer it fails outright. On the TPM path that
    went unnoticed, since use_systemd_initramfs had already rewritten the
    list into an order that happens to work. On a machine with no TPM
    archinstall's own rewrite leaves no kms hook at all, plymouth landed at
    index 2 - ahead of any DRM driver - and the result was a blank screen
    exactly where the LUKS passphrase is wanted (#61, and again #86).

    Blank, not absent: plymouthd is running and merely cannot render, so
    the busybox encrypt hook's `plymouth --ping` succeeds, the prompt is
    handed to plymouth, and the console fallback that would have printed
    it is skipped. The machine is live and invisible, which reads as a
    dead boot.

    BEFORE the unlocker, or the passphrase prompt is drawn on a bare
    console and the splash arrives once the disk is already open.

    Returns whether the file changed, so the caller can decide whether an
    initramfs rebuild is owed.
    """
    conf = ctx.target / "etc/mkinitcpio.conf"
    lines = []
    changed = False

    for line in conf.read_text().splitlines():
        if not line.startswith("HOOKS="):
            lines.append(line)
            continue
        hooks = line[len("HOOKS=("):].rstrip(")").split()

        # Re-place an existing plymouth rather than treating its presence as
        # proof the list is right. An earlier version skipped any line that
        # already said "plymouth", which made this function a no-op on
        # exactly the systems it exists to fix: a list carrying plymouth at
        # index 2 with no kms at all kept it, and no later run could ever
        # correct it. Measured on a disk installed from an ISO that did
        # carry the kms fix - the hooks were still udev, plymouth, keymap,
        # encrypt.
        hooks = [h for h in hooks if h != "plymouth"]

        # The list may or may not have been rewritten by
        # use_systemd_initramfs already - the TPM and non-TPM paths differ
        # in that - so this reads what is actually there rather than
        # assuming either shape.
        #
        # archinstall writes its own HOOKS line, and on the non-HSM path it
        # reverts the whole list to the legacy busybox shape: systemd ->
        # udev, sd-vconsole -> keymap consolefont. That rewrite drops kms
        # entirely, so a passphrase-only install had no kms to anchor on and
        # an earlier version fell back to udev - which put plymouth at index
        # 2, ahead of any DRM driver, and is exactly the blank screen #61
        # describes. Adding kms is the fix: falling back to an anchor that
        # cannot satisfy the invariant only moves the failure out of sight.
        anchor = next((i for i, h in enumerate(hooks) if h == "kms"), None)
        if anchor is None:
            # after modconf where Arch's own list puts it: kms loads the
            # DRM driver, and modconf is what makes module options
            # available to it. Falling back to udev would put both kms and
            # plymouth ahead of autodetect, which is not an order any
            # stock configuration uses.
            anchor = -1
            for candidate in ("modconf", "udev", "systemd"):
                if candidate in hooks:
                    anchor = hooks.index(candidate)
                    break
            hooks.insert(anchor + 1, "kms")
            anchor += 1
        hooks.insert(anchor + 1, "plymouth")

        # The invariant the docstring claims, checked rather than trusted.
        # An image that boots to a black screen at the passphrase prompt is
        # worse than an install that stops here and says why.
        placed = hooks.index("plymouth")
        unlocker = next(
            (i for i, h in enumerate(hooks) if h in UNLOCK_HOOKS), None
        )
        if unlocker is not None and placed > unlocker:
            raise RuntimeError(
                f"plymouth landed at {placed}, after the unlocker at "
                f"{unlocker}: HOOKS=({' '.join(hooks)})"
            )
        # The other half of the invariant, which went unchecked and is the
        # one that actually broke: plymouth after the unlocker is a prompt
        # on a bare console, plymouth before kms is no prompt at all.
        kms = hooks.index("kms")
        if placed < kms:
            raise RuntimeError(
                f"plymouth landed at {placed}, before kms at {kms}: "
                f"HOOKS=({' '.join(hooks)})"
            )

        rewritten = f"HOOKS=({' '.join(hooks)})"
        lines.append(rewritten)
        # compared against the line as read: now that an existing plymouth
        # is re-placed rather than skipped, a list that was already correct
        # comes out identical and owes no rebuild
        changed = changed or rewritten != line

    if changed:
        conf.write_text("\n".join(lines) + "\n")
        info("› initramfs: plymouth ahead of the unlocker")
    return changed


def add_splash_cmdline(ctx: InstallContext) -> None:
    """Ask the kernel to be quiet and the splash to come up.

    Without `splash` plymouth shows nothing, and without `quiet` the
    kernel's own messages are drawn over it - the splash is there but
    scrolled off by the time anyone looks.

    The reason a splash could hide the passphrase prompt is fixed at its
    source rather than here: ashlaros-branding now depends on ttf-dejavu,
    the font its theme names. Without it fc-match answered with an empty
    path at mkinitcpio time and plymouth had no font to draw with, so it
    rendered nothing while still answering `plymouth --ping` - which is
    what made the `encrypt` hook hand it the prompt and skip the console
    fallback (#86).

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


def add_verbose_entry(ctx: InstallContext) -> None:
    """A second boot entry that says what went wrong.

    The shipped entry carries `quiet splash`, and nothing configures a
    serial console, so a boot that dies after the menu prints nothing
    anywhere: the framebuffer is suppressed and the serial log ends at the
    countdown. A black screen is then the only symptom, on a machine whose
    owner has no way to get further.

    This copies each entry, drops both flags, and keeps everything else -
    the same kernel, the same initramfs, the same root and LUKS options -
    so choosing it is the difference between a black screen and a readable
    error. `console=ttyS0` goes on too: it costs nothing on hardware with
    no serial port, and in a VM it puts the whole boot in the host's log,
    which is where a bug report can come from.

    No sort-key on either: measured with `bootctl list`, an entry that has
    one sorts ahead of every entry that does not, so giving the verbose
    copy a "later" key would make it the default boot rather than the
    second line. Filename order already puts the ordinary entry first.
    """
    entries = sorted((ctx.target / "boot/loader/entries").glob("*.conf"))
    if not entries:
        error("no loader entries to copy; there will be no verbose entry")
        return

    for entry in entries:
        # skip what this already wrote, or a re-run copies the copy
        if entry.stem.endswith("-verbose"):
            continue
        target = entry.with_name(f"{entry.stem}-verbose.conf")
        if target.exists():
            continue
        rewritten = []
        for line in entry.read_text().splitlines():
            if line.startswith("title"):
                rewritten.append(f"{line} (verbose, for diagnosing a failed boot)")
            elif line.startswith("options"):
                words = [w for w in line.split() if w not in ("quiet", "splash")]
                words.append("console=tty0")
                words.append("console=ttyS0,115200")
                rewritten.append(" ".join(words))
            else:
                rewritten.append(line)
        target.write_text("\n".join(rewritten) + "\n")
    info("› boot entries: a verbose one beside each, for a boot that fails")


def drop_autodetect(ctx: InstallContext) -> bool:
    """Remove the autodetect hook, whatever else the install did.

    Split out of use_systemd_initramfs because that one runs only on the
    TPM path and this has to happen on all of them. Idempotent: an install
    that already went through use_systemd_initramfs finds nothing to do.

    Returns whether the file changed, so the caller knows whether a
    rebuild is owed.
    """
    conf = ctx.target / "etc/mkinitcpio.conf"
    lines = []
    changed = False

    for line in conf.read_text().splitlines():
        if not line.startswith("HOOKS=") or "autodetect" not in line:
            lines.append(line)
            continue
        hooks = [h for h in line[len("HOOKS=("):].rstrip(")").split() if h != "autodetect"]
        lines.append(f"HOOKS=({' '.join(hooks)})")
        changed = True

    if changed:
        conf.write_text("\n".join(lines) + "\n")
        info("› initramfs: every module, not just the installer's hardware")
    return changed


def configure_splash(ctx: InstallContext) -> None:
    """Select the theme and make sure the initramfs carries it.

    plymouth-set-default-theme -R would rebuild the initramfs itself, which
    on an encrypted install is a second rebuild racing the one
    add_crypttab_tpm_option already does. So the theme is set without -R
    and the rebuild is done once, here, after every hook edit is in place.
    """
    # Before anything else, and on every install: autodetect prunes the
    # initramfs to the hardware mkinitcpio can see, and mkinitcpio runs
    # under arch-chroot on the live ISO - so it keeps the INSTALLER's
    # drivers. Only bochs, which is what the ISO's own -vga std uses.
    #
    # use_systemd_initramfs drops it, but its one caller is
    # add_crypttab_tpm_option, which runs only after a TPM enrolment. A
    # passphrase-only install therefore shipped an initramfs with no
    # driver for the display it was about to boot on, plymouth found no
    # DRM device, and the splash - and with it the passphrase prompt the
    # encrypt hook had already handed over - rendered nothing at all
    # (#86). Measured: the probe frame was pure (0,0,0), where a splash
    # that drew even its own background would have been #141A1B.
    drop_autodetect(ctx)

    theme = ctx.target / "usr/share/plymouth/themes/ashlaros/ashlaros.plymouth"
    if not theme.exists():
        info("› no ashlaros plymouth theme installed, leaving the boot bare")
        return

    run_command(
        ["arch-chroot", str(ctx.target), "plymouth-set-default-theme", "ashlaros"]
    )
    use_plymouth_initramfs(ctx)
    add_splash_cmdline(ctx)
    # after the flags are on, so the copy is of the final entry
    add_verbose_entry(ctx)
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
    _unlock_keyring_at_login(ctx)


def _append_pam_lines(path: Path, lines: list[str]) -> None:
    """Add PAM lines to a stock file, once.

    Appended rather than replaced because both files are package-owned -
    /etc/pam.d/greetd by greetd and /etc/pam.d/passwd by shadow - so
    shipping either as package payload would be a file conflict, and
    overwriting one here would produce a .pacnew on the next upgrade of a
    package we do not control.
    """
    if not path.exists():
        return
    existing = path.read_text()
    new = [line for line in lines if line not in existing]
    if not new:
        return
    path.write_text(existing.rstrip("\n") + "\n" + "\n".join(new) + "\n")


def _unlock_keyring_at_login(ctx: InstallContext) -> None:
    """Unlock the login keyring with the password already being typed.

    gnome-keyring is installed on every machine and its daemon starts, but
    without PAM the keyring is never unlocked - so the first thing wanting
    a secret (a saved browser password, a Wi-Fi PSK, an ssh key) prompts
    for a keyring password the user may never have set deliberately.

    `optional` on both lines is deliberate and load-bearing: a keyring
    failure must never be able to deny a session. Authentication is
    decided by the system-local-login stack these files include; this only
    hands that password on to the keyring afterwards.
    """
    pam_dir = ctx.target / "etc/pam.d"

    # greetd: unlock at login. auto_start creates the keyring on first
    # login for a user who has none yet.
    _append_pam_lines(
        pam_dir / "greetd",
        [
            "auth       optional     pam_gnome_keyring.so",
            "session    optional     pam_gnome_keyring.so auto_start",
        ],
    )

    # passwd: keep the keyring password in step with the account password.
    # The one that gets forgotten, and whose absence fails weeks later -
    # `passwd` changes the account password, the keyring keeps the old
    # one, and unlocking silently stops working with no obvious cause.
    _append_pam_lines(
        pam_dir / "passwd",
        ["password   optional     pam_gnome_keyring.so"],
    )

    # Autologin means no password is typed, so PAM has nothing to unlock
    # with and the keyring still prompts on first use. The alternative is
    # a blank keyring password, which stores its contents unencrypted -
    # not something to do silently on a user's behalf, even with the disk
    # encrypted. Said out loud rather than left to be discovered.
    if ctx.autologin:
        info("› keyring: autologin types no password, so it prompts on first use")


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
    # half an hour before a snapshot may be cleaned. Measured on a real
    # install: twenty transactions in four minutes leave 82 snapshots and
    # cleanup removes none of them, because every one is younger than this
    # - the count only falls to the limit once they age past it. That is
    # the intended behaviour (an update that breaks the machine must still
    # have its snapshot half an hour later) but it means the bound is
    # NUMBER_LIMIT plus whatever half an hour of transactions produces,
    # not NUMBER_LIMIT.
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
        # `ufw default` writes policy and nothing else: ENABLED stays "no"
        # in /etc/ufw/ufw.conf, and ufw.service honours that flag - so
        # enabling the unit alone starts a firewall that is switched off.
        # Verified on an installed machine, where `ufw status` read
        # "inactive" with the service enabled.
        #
        # --force because `ufw enable` prompts about disrupting ssh, and
        # there is no one at the other end of an install.
        ["--force", "enable"],
    ):
        run_command(["arch-chroot", str(ctx.target), "ufw", *args])
    info("› firewall active: denies incoming, allows outgoing")


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
    """Let chwd configure this machine's hardware - all of it, not the GPU.

    This asked for `-a 0300`, PCI class 0300, display controllers. chwd
    ships six profile sets and that used one of them: network_drivers
    (Broadcom wireless, with an exact device-id list, a module blacklist
    and an initramfs rebuild), t2-macbook, power_management, handhelds,
    and profiles/usb/fprint were all being discarded (#66).

    `-a` takes the class id as an OPTIONAL argument - `[<classid>]` in
    --help, checked against the shipped 1.24.1 rather than inferred - and
    bare it means "any", which walks every PCI and USB device that has a
    profile. ai_sdk is gated behind its own --ai_sdk flag, so widening
    does not pull in an AI toolchain.

    It also gets quieter, not noisier: with a specific class id a device
    with no profile logs "No config found for device"; under any that is
    deliberately suppressed.

    A machine chwd has no profile for is still not a failure - the
    kernel's built-in drivers bring up a display - which is why this
    reports and returns rather than raising.
    """
    result = subprocess.run(
        ["arch-chroot", str(ctx.target), "chwd", "-a"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error(f"chwd found no profile to install: {result.stderr.strip()}")
        return
    info("› chwd configured the hardware it recognised")


def lock_boot_editor(ctx: InstallContext) -> None:
    """Turn off systemd-boot's kernel command-line editor.

    It defaults to on, and on a machine whose TPM unlocks the disk that is
    a full compromise in about fifteen seconds: press `e` at the menu,
    append init=/bin/bash, boot to a root shell on the decrypted
    filesystem. The TPM releases the key because PCR 7 measures Secure
    Boot policy, and editing a command line does not change Secure Boot
    policy (#63).

    Amended, never clobbered: archinstall writes this file - read off a
    real install, it carries `timeout 3` - and rewriting it wholesale
    would silently drop that.

    This does not make TPM unlock sound. With Secure Boot off, an attacker
    boots their own binary and never sees this menu; even with it on, PCR 7
    measures neither the kernel nor the initramfs. Those belong to the
    enrolment-policy question. This closes the free one.
    """
    esp = ctx.target / ctx.esp_mount.lstrip("/")
    conf = esp / "loader/loader.conf"
    conf.parent.mkdir(parents=True, exist_ok=True)

    note = "# the cmdline editor is a root shell on a TPM-unlocked disk (#63)"
    lines = conf.read_text().splitlines() if conf.exists() else []
    kept = [
        line
        for line in lines
        # Both, or a re-run stacks a second copy of the comment while the
        # setting itself stays correct - which is how this was caught.
        # An existing `editor` setting is the thing being overridden.
        if line.strip() != note
        and not line.strip().lstrip("#").strip().startswith("editor")
    ]
    kept.append(note)
    kept.append("editor no")
    conf.write_text("\n".join(kept) + "\n")
    info("› boot menu: the command-line editor is off")


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
