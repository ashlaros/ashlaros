# AshlarOS

An Arch-based distribution: plain Arch underneath, [CachyOS](https://cachyos.org)
v3-optimised repositories layered over it, `chwd` for hardware detection,
`linux-cachyos` as the kernel, systemd-boot, and a sway desktop carried over
from [manjaro-sway](https://github.com/manjaro-sway/manjaro-sway).

![The AshlarOS desktop](https://ashlaros.download/iso/latest/screenshots/desktop.png)

## Installing

The ISO is **UEFI only**. A machine in legacy or CSM mode will not see it
as bootable at all, so put the firmware in UEFI mode. The package stack is
`x86_64_v3` anyway, which already rules out machines old enough to need a
BIOS path.

Write it with `dd` or `cp` straight to the device; it is a hybrid image
with a protective MBR and a GPT, so it needs no preparation. A writer that
repacks the image can leave the EFI partition unbootable.

The installer asks four questions, each with a default, so Enter through all
of them installs: locale and keyboard, user and password, encryption, disk
layout. Encryption is on by default and the disk is LUKS2 with the root
filesystem on btrfs; the ESP is mounted at `/boot`.

### If you chose TPM unlock, a firmware update brings the passphrase back

The installer asks how the disk should unlock — passphrase, TPM + PIN, or
TPM alone — with passphrase preselected. Settings → **Disk unlock**
changes it later.

Both TPM options bind to **PCR 7**, which measures the Secure Boot policy
and key databases. A vendor firmware update that ships new `dbx` or `KEK`
contents changes it, and the enrolled keyslot stops matching.

Nothing is lost when that happens. The passphrase still unlocks the disk,
which is why there is always one. But the prompt arrives with no
explanation, and it is easy to read as a corrupted disk. It is not.
Re-enrol from the settings entry, or by hand:

```sh
sudo systemd-cryptenroll --wipe-slot=tpm2 --tpm2-device=auto --tpm2-pcrs=7 /dev/<luks-partition>
```

`fwupd` is installed and `fwupd-refresh.timer` is enabled, so LVFS metadata
stays current and `fwupdmgr get-updates` has something to say. Nothing is
ever flashed unattended: applying an update is an explicit `fwupdmgr
update`. A bad capsule bricks a board and there is no rollback from the OS
side, so that stays a decision someone makes.

## Download stats

[`ashlaros.download/iso/stats`](https://ashlaros.download/iso/stats)
counts ISO downloads, and `/stats.json` is the same data
machine-readable. A download is one whole-image request that succeeded, so
a resumed download counts once and a checksum file does not count at all.

## Settings

`ashlaros-settings-tui` (`Super+,`, or "AshlarOS Settings" in the
launcher) collects the settings that are otherwise commands you have to
know:

- locale, keyboard layout, time and timezone
- kernel variants and hardware profiles
- fingerprint enrolment, face unlock, adaptive brightness, power profiles
- how the disk unlocks, and snapshots
- the wallpaper, and packages nothing needs any more

It also opens the things that do nothing until configured: mail, a
calendar, notes, chat clients, web apps and a model. Displays and package
installation open `ashlaros-displays` and `pacseek`.

**A launcher, not a control panel.** Every entry runs an existing tool, or
collects what it needs and runs one command. Entries hide themselves when
their program is missing, or when the machine has no hardware for them, so
nothing on screen can fail halfway. Root is asked for per action, not for
the whole menu.

Installing a kernel is an entry; **which kernel boots stays the boot
menu's own choice**. After an install it checks that the new kernel can
actually boot, and says plainly if something is missing.

## Face unlock

Not installed, and off even when it is. Install `howdy-next` and, on a
machine with a camera, Settings → **Face unlock** enrols a face, tests it,
and can turn it on for `sudo`.

**It is weaker than a password**, and upstream says so first: a similar
face or a photo may work. This is 2D infrared matching, not Windows Hello.

It is used for `sudo` only, never the lock screen and never the greeter,
and it is never enabled until a recognition test has passed. A face that
fails, in a dark room or at an odd angle, falls through to the password
that always worked. Turning it off restores the original configuration
exactly. The disk passphrase is untouched either way.

It costs 182 packages to install, which is why nobody who does not want it
pays for it.

## Notes

`zk` is installed. Settings → **Notes** creates a notebook in your
documents directory, so `~/Documents/notes` on an English system, and
offers to make it a git repository.

The notes are plain Markdown files in a directory. There is no format of
ours to export and nothing to sync, so backing them up is `git init`. A
note stays readable and editable with or without `zk`.

**Nothing is ever committed for you.** A tool that commits notes by itself
is one that can push a private notebook somewhere you did not choose. The
repository is offered; the commits are yours.

`zk` ships an LSP server, so `[[wikilink]]` completion works in `helix`
without a plugin.

## The prompt

`starship` is configured out of the box, with the mark rendered as three
courses of stone: `▄█▀`. It follows the desktop theme, and a theme change
reaches the shell you are already sitting in.

If you edit the config by hand, **starship needs six-digit hex**. Given
`#eee` it accepts the file and silently renders that style unstyled.

## Mail and calendar

Neither is preinstalled and neither does anything until you configure it.

[`khal`](https://khal.readthedocs.io) **is** installed, with a keybind,
and Settings → **Calendar** syncs it against a CalDAV server on a timer. A
local calendar exists before any of that, so a machine with no account
still has somewhere to put an appointment.

Nextcloud, Fastmail, iCloud, mailbox.org, Posteo and Zoho come with their
URLs prefilled; "Other CalDAV server" is a first-class option. **Google**
signs in through your browser rather than a password, and the token stays
on the machine. Gmail needs one extra step the calendar does not: the
first token comes from Google's OAuth 2.0 Playground.

**Subscribed calendars** read a published `.ics` link into the same
calendar: a timetable, a fixture list, or Proton Calendar's "share via
link". You name each one and can remove them individually. They are
read-only, and they are the only way to reach **Proton**, which speaks no
CalDAV. Anyone holding such a link can read that calendar.

Settings → **Mail** configures [`aerc`](https://aerc-mail.org)
(`pacman -S aerc`) against IMAP and SMTP. Both clients keep the password
in the login keyring rather than in a config file, and aerc follows the
desktop theme.

**Outlook is not supported**, for mail or calendar: Microsoft retired
CalDAV for Outlook.com in favour of Graph, which nothing here speaks.

## Office documents

Nothing here opens a `.docx` out of the box: no suite, no viewer. That is
a floor we chose. LibreOffice is 147 MB and looks nothing like the rest of
the desktop. Install `libreoffice-still` if you need Office formats to
round-trip faithfully; it is the only thing that really does.

Settings → **Web apps** installs Google Docs, Sheets and Slides, or
Microsoft 365, as real web apps: own window, own icon, launchable from
rofi. It needs `firefoxpwa` and downloads a browser runtime of about
300 MB the first time.

`rclone` mounts Drive or OneDrive as a directory, which is the version of
"open it from the cloud" that does not involve publishing your document to
a public URL first.

## Reading the screen: text, QR codes, and asking a model

`Print` opens screenshot mode. Beside `p` and `o`, which photograph:

| key | does | leaves the machine |
| --- | --- | --- |
| `t` | OCR the selected region onto the clipboard | no |
| `q` | decode a QR in the region onto the clipboard | no |
| `a` | ask a configured model about the region | **yes** |

`t` and `q` run locally. `ASHLAROS_OCR_LANGS` selects OCR languages once
the data is installed; English ships. A decoded QR is copied but never
shown, because QR codes routinely carry secrets, 2FA URIs above all.

**`a` is the one that sends your screen somewhere.** It needs `aichat`,
which is not installed by default, and a provider you configure yourself.
There is no default provider and no bundled key. Nothing is sent unless you press
that key, and the notification names the model before the request goes
out.

Point it at a local model and it costs no privacy: `aichat` speaks to
Ollama and any OpenAI-compatible endpoint as readily as to a SaaS.

```yaml
# ~/.config/aichat/config.yaml
model: ollama:llama3
clients:
  - type: openai-compatible
    name: ollama
    api_base: http://localhost:11434/v1
    models:
      - name: llama3
```

Configure a hosted provider instead and a picture of part of your screen
goes to that company. That is why this sits behind its own key, in an
optional package, unconfigured.

## AppImages

They run. `fuse2` and `fuse3` are installed, which is all an AppImage
needs. Nothing integrates them into the launcher by itself:
download, `chmod +x`, run. [Gear Lever](https://gearlever.mijorus.it) is
the current tool for managing and updating them.

`flatpak` is installed but **no remote is configured**. Adding Flathub is
one command, and it is left to you. Flathub is a third-party software
source, and an installer should not enable one without asking.

```sh
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

The update badge counts flatpak updates once you have some, and `topgrade`
updates them alongside everything else.

## Displays

`ashlaros-displays` (`Alt+d`, beside the scale keybinds) configures
displays: per-display scale, mode, rotation, VRR and enable/disable, plus
arrangement, order and the scaling globals.

**There are no profiles, deliberately.** The model is reactive rather than
selected: a configuration describes what should be true for a set of
connected displays, and it is applied whenever that set changes. Plugging
the dock *is* the switch, so "when I dock, use this layout" is a rule, not
a profile you pick.

If you hand-edit `~/.config/way-displays/cfg.yaml`, know that **comments
and formatting are destroyed** the next time anything saves a change.

## Snapshots, and what recovery actually involves

The default layout is btrfs, with `snapper` and `snap-pac` installed.
Every pacman transaction takes a snapshot first, so one always exists from
*before* the upgrade that broke things. `ashlaros-snapshot create` takes
one on demand and `list` shows what is there. Twelve are kept, one per
package transaction rather than one per hour.

**Rollback is a rescue-media procedure, not a boot-menu one**, and
`snapper rollback` is not the command. On this layout it can report
success while leaving the machine still broken. What works is replacing
the root subvolume. Verified end to end: a machine with a deliberately
destroyed `/etc/os-release` came back reading `AshlarOS` with `$HOME`
intact and a deleted binary restored.

1. Boot the AshlarOS ISO.
2. Unlock the disk — `cryptsetup open /dev/nvme0n1p2 root`. Use the
   passphrase, not the TPM: a firmware update can invalidate the TPM
   keyslot, and this is the credential that always works.
3. Mount the **top level**, which is where the subvolumes live:

   ```sh
   mount -o subvolid=5 /dev/mapper/root /mnt
   ls /mnt                      # @  @home  @log  @pkg
   ls /mnt/@/.snapshots         # the snapshots, numbered
   ```

4. Put the broken root aside and take the snapshot's place:

   ```sh
   mv /mnt/@ /mnt/@.broken
   btrfs subvolume snapshot /mnt/@.broken/.snapshots/<number>/snapshot /mnt/@
   ```

5. Reboot, and delete `@.broken` once the machine is known good.

`$HOME` survives, because it is its own subvolume and only the root is
replaced. The journal recording the failure and the package cache both
outlive the rollback for the same reason.

On an ext4 install none of this exists, and `ashlaros-snapshot` tells you
so. A snapshot tool that stays quiet when it cannot work leaves you
believing you have backups.

## Using the repository on an existing system

The `ashlaros` repository is dual-arch: `x86_64` and `aarch64`. The ISO is
x86_64; ARM users get either the prebuilt Pi 5 image below or these packages
on an existing Arch Linux ARM system.

```sh
# 1. trust the signing key
curl -fsSL https://ashlaros.download/packages/ashlaros.gpg -o /tmp/ashlaros.gpg
sudo pacman-key --add /tmp/ashlaros.gpg
sudo pacman-key --lsign-key "$(gpg --show-keys --with-colons /tmp/ashlaros.gpg | awk -F: '/^fpr:/ {print $10; exit}')"

# 2. add the repository
printf '[ashlaros]\nSigLevel = Required DatabaseRequired\nServer = https://ashlaros.download/packages/$arch\n' |
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
  ARM kernel or v3 userland to build one from. There is a Raspberry Pi 5
  *disk image* instead - a different thing, described below.

## The Raspberry Pi 5 image

There is a prebuilt disk image for the Pi 5, published at
[`latest/ashlaros-rpi5.img.xz`](https://ashlaros.download/iso/latest/ashlaros-rpi5.img.xz).
It is **not the ISO for another architecture**. Four of the ISO's
defining properties cannot exist on an ARM board:

| what | x86_64 ISO | Pi 5 image |
| --- | --- | --- |
| kernel | `linux-cachyos` | `linux-rpi` (the board kernel) |
| userland | CachyOS `x86_64_v3` | plain Arch Linux ARM |
| boot | systemd-boot, UEFI | Pi firmware off a FAT partition |
| install | TUI installer, LUKS + TPM | written to a card, **unencrypted** |
| hardware detection | `chwd` | none (`chwd` is x86_64 only) |

What carries over is what you see: sway, the settings TUI, the theming,
the waybar config.

Write it to a card and boot it. There is no installer, so setup happens on
first boot. The root filesystem grows to fill the card, ssh host keys are
generated for that machine, and you create an account on tty1 **before the
network comes up**. Arch Linux ARM's default `alarm` and `root` logins are
removed, and `sshd` stays off until an account exists. Otherwise the image
would reach the network carrying credentials that are published.

## Reaching other machines

`mosh` is installed everywhere - the ISO, an installed system, and the Pi
image. It is the client only. A session survives suspending the laptop,
changing network and roaming, where `ssh` drops, and it needs no terminfo
on the far end: `mosh-server` normalises `TERM` itself, which is the
workaround `.zshrc` has to apply for plain `ssh`.

**Nothing here is reachable by mosh out of the box**, and that is
deliberate. `sshd` is not enabled on any of the three, and `mosh-server`
is started over ssh. To make one machine reachable:

```sh
sudo systemctl enable --now sshd
sudo ufw allow 60001:60999/udp   # mosh-server picks one port in this range
```

The firewall stays shut for outbound use: a session you start needs no
rule at all, because the reply traffic is already `RELATED,ESTABLISHED`.

One limitation worth knowing: `COLORTERM` does not survive the link, so
programs that detect 24-bit colour from that variable rather than from
terminfo will fall back to 256 colours. Truecolor itself works.

## Contributing

Building the ISO and the packages, how versions are derived, and what the
CI does: [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
