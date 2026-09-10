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
worker/       cloudflare worker serving the pacman repository from R2
scripts/      publish tooling for the repository
```

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

Packages are built and published by `.github/workflows/build-packages.yml`.
`packages/*/PKGBUILD` are ours; `packages/upstreams.yml` lists the AUR sources
built alongside them.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
