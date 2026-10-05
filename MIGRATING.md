# Coming from Manjaro Sway

AshlarOS carries the [manjaro-sway](https://github.com/manjaro-sway/manjaro-sway)
desktop over to a different base. The sway config, the keybindings and most
of the themes are the same. What sits underneath is not: plain Arch with
CachyOS's repositories instead of Manjaro, and different tools in a few
places. Manjaro Sway is in maintenance mode, and new work happens here.

## There is no in-place upgrade

**Moving over is a fresh install.** A Manjaro system cannot be switched to
AshlarOS by changing repositories. The two use different kernels, different
hardware detection and different bootloaders, and their settings packages
own the same files. A half-converted system is harder to recover than a
clean one.

**The installer erases the whole disk you pick.** It has no option to
install beside another system or to keep a partition. Back up first, to a
separate drive.

## Check the machine first

AshlarOS needs two things Manjaro Sway did not.

**An x86-64-v3 CPU.** The packages are built for it, which needs AVX2:
roughly Intel Haswell or AMD Excavator (2013 and later). Check on the
machine you want to move:

```sh
/lib64/ld-linux-x86-64.so.2 --help | grep x86-64-v3
```

`x86-64-v3 (supported, searched)` means it can run AshlarOS. No line, or no
`supported`, means it cannot.

**UEFI boot.** The ISO has no BIOS boot path. This prints `UEFI` on a
machine that booted that way:

```sh
[ -d /sys/firmware/efi ] && echo UEFI
```

If it prints nothing, switch the firmware from legacy or CSM mode to UEFI
before installing. Manjaro installed in BIOS mode will not boot after that
switch, so do it only when you are ready to reinstall.

On a **Raspberry Pi**, the AshlarOS image is built for the Pi 5 and is
unencrypted. See [the Raspberry Pi 5 image](README.md#the-raspberry-pi-5-image).

## 1. Back up

Copy your home directory to an external drive. Then save the things that
live outside it, or that the new system reads differently:

```sh
# the packages you installed yourself, to reinstall the ones you still want
pacman -Qqe > ~/pkglist.txt

# your calendar, if you used calcurse; AshlarOS uses khal instead
calcurse --export > ~/calendar.ics

# saved Wi-Fi networks, which live outside your home directory
sudo cp -a /etc/NetworkManager/system-connections ~/wifi-backup
```

The Wi-Fi files contain the network passwords in plain text. Keep that copy
somewhere private, and delete it once you are done.

## 2. Install AshlarOS

Download the ISO from [ashlaros.download](https://ashlaros.download/), write
it to a USB stick and boot it. [Installing](README.md#installing) in the
README covers the installer screens, disk encryption and TPM unlock.

## 3. Bring your files back

**Restore your data, not your whole `~/.config`.** Documents, pictures,
SSH and GPG keys, browser profiles and application data all copy back
unchanged.

The desktop's own config files are a different matter. AshlarOS ships newer
versions of many of them, and fixes some on login when they are the ones it
shipped. Copying the Manjaro Sway versions back over them can bring back
configs for tools that are gone (rofi, nwg-wrapper) and undo those fixes.
Bring back only the parts you wrote yourself:

- **Sway overrides:** `~/.config/sway/config.d/*.conf` are read exactly as
  before. Copy them back.
- **A theme you made:** a `theme.conf` you wrote still works, because the
  format is unchanged. Copy it to `~/.config/sway/definitions.d/theme.conf`.
  The GTK, icon and cursor themes it names must be installed.
- **Your shell:** do not copy the old `~/.config/zsh/.zshrc`. It loads
  Manjaro's zsh config and powerlevel10k, which Arch does not have. Copy
  your aliases and functions into the new file instead.

Then the rest:

```sh
# packages: review the list first, since some names are Manjaro-only
sudo pacman -S --needed $(grep -vxE 'manjaro.*|pamac.*|mhwd.*|calamares.*' pkglist.txt)

# calendar
khal import -a local calendar.ics

# Wi-Fi: NetworkManager ignores the files unless root owns them
sudo cp -a wifi-backup/. /etc/NetworkManager/system-connections/
sudo chown root:root /etc/NetworkManager/system-connections/*
sudo chmod 600 /etc/NetworkManager/system-connections/*
sudo systemctl restart NetworkManager
```

pacman lists every name it cannot find and then installs nothing. Remove
those names from the list and run it again, or install them from the AUR
with `yay`.

If you restored too much and the desktop misbehaves, `skel` copies the
shipped defaults back over your home directory. It backs up everything it
replaces first.

## What changed

| | Manjaro Sway | AshlarOS |
| --- | --- | --- |
| base | Manjaro, `unstable` branch | Arch, with CachyOS's v3 repositories |
| kernel | Manjaro's kernels | `linux-cachyos` |
| drivers | `mhwd` | `chwd` (Settings → Hardware profiles) |
| bootloader | GRUB | systemd-boot |
| installer | Calamares | a terminal installer |
| installing software | `pamac` | `pacseek` (Settings → Install packages), `yay` |
| launcher and pickers | rofi | fuzzel |
| calendar | calcurse | khal, with CalDAV sync (Settings → Calendar) |
| shell prompt | oh-my-zsh and powerlevel10k | Arch's grml zsh config and starship |
| keybinding help | nwg-wrapper | eww, which also shows bindings while you hold a modifier |
| choosing a theme | `manjaro-sway-theme` | Settings → Appearance |
| location override | `MANJARO_SWAY_GEO_URL` | `ASHLAROS_GEO_URL` |

**Keybindings carry over unchanged.** Two are new: `Super+,` opens Settings
and `Alt+d` configures displays. `Super+?` lists every binding.

**Themes:** the four catppuccin and four matcha themes still exist.
atari-classic, dracula and nordic-bluish-accent are gone, and ashlaros,
ashlaros-light, gruvbox, gruvbox-light and hackerman are new.

**Gone without a replacement:** the zeit time-tracking and Valent (KDE
Connect) bar modules, and `manjaro-sway-align`. `manjaro-sway-mirrors` is
not needed: the installer configures the `ashlaros` repository, and the
`ashlaros-mirrorlist` package keeps its server list.

## Getting help

Report problems in the
[AshlarOS issue tracker](https://github.com/ashlaros/ashlaros/issues). The
[Manjaro Sway chat](https://matrix.to/#/#manjaro-sway:matrix.org) is still
open for questions about moving over.
