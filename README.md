# AshlarOS

An Arch-based distribution: plain Arch underneath, [CachyOS](https://cachyos.org)
v3-optimised repositories layered over it, `chwd` for hardware detection,
`linux-cachyos` as the kernel, systemd-boot, and a sway desktop carried over
from [manjaro-sway](https://github.com/manjaro-sway/manjaro-sway).

One repository holds everything: the packages we build, the ISO profile, the
installer, and the branding.

```
packages/     PKGBUILDs published to the ashlaros pacman repository
iso/          the archiso profile the ISO is built from
installer/    the gum TUI installer shipped on the ISO
branding/     logo, favicon, background, palette
worker/       cloudflare worker serving the repository and the ISOs from R2
scripts/      publish tooling for the repository
```

## Installing

The ISO is **UEFI only**: `bootmodes=('uefi.systemd-boot')`, so the image
carries one El Torito entry and no BIOS one. A machine in legacy or CSM
mode does not see it as bootable at all. That is deliberate — the package
stack is `x86_64_v3`, which already excludes every machine old enough to
need a BIOS path — but the firmware has to be in UEFI mode.

Write it with `dd` or `cp` straight to the device; it is a hybrid image
with a protective MBR and a GPT, so it needs no preparation. A writer that
repacks the image can leave the EFI partition unbootable.

The installer asks four questions, each with a default, so Enter through all
of them installs: locale and keyboard, user and password, encryption, disk
layout. Encryption is on by default and the disk is LUKS2 with the root
filesystem on btrfs; the ESP is mounted at `/boot`.

### After a firmware update, expect a passphrase prompt

If the machine has a TPM, the installer enrols the LUKS passphrase against
**PCR 7**, so an ordinary boot unlocks without typing anything. PCR 7
measures the Secure Boot policy and key databases. A vendor firmware update
that ships new `dbx` or `KEK` contents therefore changes it, and the
enrolled keyslot stops matching.

Nothing is lost when that happens — the passphrase still unlocks the disk,
which is why the installer requires one. But the prompt arrives with no
explanation, and it is easy to read as a corrupted disk. It is not. Re-enrol
afterwards:

```sh
sudo systemd-cryptenroll --wipe-slot=tpm2 --tpm2-device=auto --tpm2-pcrs=7 /dev/<luks-partition>
```

`fwupd` is installed and `fwupd-refresh.timer` is enabled, so LVFS metadata
stays current and `fwupdmgr get-updates` has something to say. Nothing is
ever flashed unattended: applying an update is an explicit `fwupdmgr
update`. A bad capsule bricks a board and there is no rollback from the OS
side, so that stays a decision someone makes.

### yay is installed

An AUR helper ships with the desktop, from the `cachyos` repository rather
than vendored here. It is not a convenience: every shipped theme lists the
packages it needs, and the four catppuccin themes name AUR-only ones, so
the theme switcher cannot do its job without a helper present.

What that means is worth stating rather than leaving implicit. The AUR is
arbitrary code from arbitrary maintainers, built and run on the machine at
install time. Shipping `yay` puts that one command away instead of two. It
is the usual trade for an Arch-derived desktop, and the same one
manjaro-sway made, but it is a real one — `pacman -R yay` removes it, and
the theme switcher then says which packages it would have needed.

## Using the repository on an existing system

The `ashlaros` repository is dual-arch: `x86_64` and `aarch64`. The ISO is
x86_64 only, but the packages install on Arch Linux ARM just as well.

```sh
# 1. trust the signing key
curl -fsSL https://packages.ashlaros.download/ashlaros.gpg -o /tmp/ashlaros.gpg
sudo pacman-key --add /tmp/ashlaros.gpg
sudo pacman-key --lsign-key "$(gpg --show-keys --with-colons /tmp/ashlaros.gpg | awk -F: '/^fpr:/ {print $10; exit}')"

# 2. add the repository
printf '[ashlaros]\nSigLevel = Required DatabaseRequired\nServer = https://packages.ashlaros.download/$arch\n' |
  sudo tee -a /etc/pacman.conf

# 3. install
sudo pacman -Sy ashlaros-keyring ashlaros-mirrorlist ashlaros-settings
```

Afterwards `ashlaros-mirrorlist` owns the server list, so the `Server =` line
above can be replaced with `Include = /etc/pacman.d/ashlaros-mirrorlist`.

## What this is not

- **Not Manjaro.** No `mhwd`, no `manjaro-system`, no Manjaro rebuilds, no
  calamares. Plain Arch provides what those did; `chwd` replaces `mhwd`.
- **Not for pre-Haswell CPUs.** The ISO's package stack is `x86_64_v3`, which
  requires AVX2. Machines older than 2013 cannot run it.
- **Not an ARM ISO.** CachyOS publishes no ARM repositories, so there is no
  ARM kernel or v3 userland to build one from. ARM users run Arch Linux ARM
  and add this repository on top.

## Building

The ISO is built by `.github/workflows/build-iso.yml` with `archiso`. To build
it locally, on an Arch host with `archiso` installed:

```sh
sudo mkarchiso -v -w /tmp/ashlaros-work -o out iso/
```

Packages are built and published by `.github/workflows/build-packages.yml`,
in dependency waves: a package that needs another built here waits for it to
be published first.

`packages/ashlaros-*` are ours, and their versions are derived rather than
written down: `pkgver` is the date of the last commit touching the package
directory and `pkgrel` the number of such commits, both stamped at build
time by `scripts/package_version.py`. Editing a config under
`packages/ashlaros-settings/payload/` and committing is therefore the whole
release process — the version moves, so `pacman -Syu` sees an upgrade. A
hardcoded version would strand that edit: pacman compares versions, not
contents. The rest are vendored from the AUR, because
an AUR PKGBUILD can be force-pushed between two builds of the same version.
`packages/upstreams.yml` records where each came from — the AUR for most,
GitHub for three — and `.github/workflows/track-upstreams.yml` checks all of
them daily, opening one pull request per package that moved. Several of them carry local edits — `arch=` widened to
aarch64, a broken man-page step removed — so that merge is three-way against
`packages/.upstream/` and conflicts are left for a human. Nothing merges
itself.

## Testing

Most of what matters here is only observable at runtime — the ISO boots
UEFI-only, the installer is a TUI, the desktop is sway. `test/vm/` boots a
published ISO under QEMU with a software TPM, drives the installer through
its four screens, and lets a command be typed on the installed system:

```sh
test/vm/run.sh fetch
test/vm/run.sh install
```

See [test/vm/README.md](test/vm/README.md); it takes about 35 minutes,
because there is no KVM inside the container.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
