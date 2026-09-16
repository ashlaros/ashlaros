# AshlarOS

An Arch-based distribution: plain Arch underneath, [CachyOS](https://cachyos.org)
v3-optimised repositories layered over it, `chwd` for hardware detection,
`linux-cachyos` as the kernel, systemd-boot, and a sway desktop carried over
from [manjaro-sway](https://github.com/manjaro-sway/manjaro-sway).

![The AshlarOS desktop](https://ashlaros.download/iso/latest/screenshots/desktop.png)

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

### If you chose TPM unlock, a firmware update brings the passphrase back

The installer asks how the disk should unlock — passphrase, TPM + PIN, or
TPM alone — with passphrase preselected. Settings → **Disk unlock**
changes it later.

Both TPM options bind to **PCR 7**, which measures the Secure Boot policy
and key databases. A vendor firmware update that ships new `dbx` or `KEK`
contents changes it, and the enrolled keyslot stops matching.

Nothing is lost when that happens — the passphrase still unlocks the disk,
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

## Download stats

`ashlaros.download/iso/stats` counts ISO downloads, and `/stats.json` is
the same data machine-readable. A download is one whole-image `GET` that
returned `200`: a resumed download issues many range requests and would
otherwise report one image as dozens, a revalidation transfers nothing,
and `SHA256SUMS` is not a download. Only the ISO site counts — every
`pacman -Sy` is a database fetch and would drown the signal. Images taken
from `/latest/` have no version in their URL and are counted as their own
row: that is how many people take the current image without pinning one.

Two stores, because neither works alone. Analytics engine takes the writes
— `writeDataPoint` is non-blocking, so counting costs a download nothing —
but retains three months. KV keeps the archive, written once a month by a
cron on the 2nd rather than per download: KV allows one write per second
per key and propagates for up to a minute, so a per-download counter would
lose counts to last-write-wins. The 2nd, not the 1st, because a closed
month's last events have to be queryable before it is archived.

Writing needs no credentials; reading does. Analytics engine has no query
binding, so the page reads over the SQL API with a token
(`wrangler secret put ANALYTICS_TOKEN`, scoped *Account · Account
Analytics · Read*). Downloads are counted whether or not the token is set,
so it can be added later without losing anything; until it is, the page
says so rather than answering 500.

## Settings

`ashlaros-settings-tui` (`Super+,`) is one entry point for the settings
that are otherwise commands you have to know: locale and keyboard layout,
time and timezone, kernel variants from the cachyos repository, chwd's
hardware profiles, fingerprint enrolment, face unlock, adaptive
brightness, power profiles, how the disk unlocks, snapshots, the
wallpaper, packages nothing needs any more, and a door to the things that
need setting up before they do anything — mail, a calendar, notes, chat
clients, web apps and a model. Displays and package installation dispatch
to `ashlaros-displays` and `pacseek`.

**A launcher, not a control panel.** Every entry either runs an existing
tool or collects input and runs one command; the menu owns no settings
logic. An entry whose binary is not installed is absent rather than
present and broken — and so is one whose hardware is missing, or whose
packages this architecture cannot install, since an entry that cannot
finish is worse than one that is not there.

Root is taken per action rather than by running the whole thing under
`sudo` — a long-running root TUI on a desktop is a bigger blast radius
than it needs.

The kernel entry installs; **which kernel boots stays systemd-boot's own
menu**, which already lists every entry and cannot leave a machine
unbootable. After an install it checks the three things that decide whether
the new kernel can boot at all — the `mkinitcpio.d` preset, an image in
`/boot`, and a loader entry naming it — and says plainly when one is
missing. A kernel package ships nothing in `/boot`, only
`usr/lib/modules/<kver>/vmlinuz`, and mkinitcpio's hook copies it only if a
preset named for the pkgbase exists; without one the machine gains an entry
that silently does not boot. It reports rather than repairs: writing a
preset for a kernel we did not package is guesswork.

## Face unlock

Not installed, and off even when it is. `howdy-next` is an `optdepends`;
with it installed on a machine that has a camera, Settings → **Face
unlock** enrols a face, tests it, and can turn it on for `sudo`.

**It is weaker than a password**, and upstream says so first: a similar
face or a photo may work. This is 2D infrared matching, not Windows Hello
— Hello's anti-spoofing comes from a dot projector building a depth map,
and Howdy reads a flat frame.

The PAM rules match the fingerprint entry's: `sufficient` before the
password line, `sudo` only, never the lock screen or the greeter, and
never enabled until a recognition test has passed. A face that fails — a
dark room, a covered emitter, a lid at an angle — falls through to the
password that always worked. Verified with `pam_howdy.so` absent entirely,
the worst case: `sudo` still accepts a password. Disabling restores
`/etc/pam.d/sudo` byte-identically to the file pacman ships, so no
`.pacnew` appears. The disk passphrase is untouched either way: LUKS
happens long before PAM exists.

It costs 182 packages — `opencv` alone is 112.81 MiB — which is why nobody
who does not want it pays for it. `linux-enable-ir-emitter`, which turns
on the emitters many laptops leave dark, is **not** packaged: its current
release builds against `opencv4` and Arch now ships `opencv` 5.

## Notes

`zk` is installed. Settings → **Notes** creates a notebook — in the
localised documents directory, so `~/Documents/notes` on an English
system — and offers to make it a git repository.

The notes are plain Markdown files in a directory, which is the whole
reason for choosing it: there is no format of ours to export and nothing
to sync, so "my notes are backed up" is `git init` and nothing more. A
note is readable, and editable, with or without `zk`.

**Nothing is ever committed for you.** A tool that commits notes by itself
is one that can push a private notebook somewhere you did not choose. The
repository is offered; the commits are yours.

The `.gitignore` excludes `.zk/notebook.db`: `zk` rebuilds that index from
the notes with `zk index`, so it is derived state, and it is a binary that
changes on every command — committing it would make every commit a
conflict.

`zk` ships an LSP server, so `[[wikilink]]` completion works in `helix`
without a plugin.

## The prompt

`starship` is configured in skel, with the mark rendered as three courses
of stone: `▄█▀`, a solid course between one stepping down and one stepping
up. It is not the logo — 40 columns of dressed stone do not survive being
shrunk to a prompt — and it is not `▞`, which reads as two specks at that
size in the font we ship.

`generate-starship-config.sh` rewrites it on a theme switch, beside the
waybar and aerc generators. It is the cheapest of the three: starship
re-reads its config every prompt, so a theme change reaches the shell you
are already sitting in.

One thing worth knowing if you edit the config by hand: **starship needs
six-digit hex.** Given `#eee` it accepts the file, silently drops the
whole style string that colour appears in, and renders unstyled.

## Mail and calendar

Neither is preinstalled and neither does anything until you configure it:
a client that opens onto nothing is worse than no client.

[`khal`](https://khal.readthedocs.io) **is** installed, with a keybind,
and Settings → **Calendar** points
[`vdirsyncer`](https://vdirsyncer.pimutils.org) at a CalDAV server on a
timer. A local calendar exists before any of that, so a machine with no
account still has somewhere to put an appointment.

Nextcloud, Fastmail, iCloud, mailbox.org, Posteo and Zoho come with their
URLs prefilled; "Other CalDAV server" is a first-class option. vdirsyncer
refuses a sync that would empty both sides, and the conflict question is
asked as *which copy wins* rather than in its own "a wins"/"b wins" terms.

**Google** signs in through a browser rather than a password. AshlarOS
ships an OAuth client registration, the way every desktop offering Google
accounts does — GNOME bakes the same two values into
`gnome-online-accounts`. It identifies the application, not you: the
sign-in happens against your own account and the token never leaves the
machine. Put your own `client_id` and `client_secret` in
`~/.config/ashlaros/google-oauth-client` to use your own Cloud project.
Gmail needs one extra step the calendar does not — the initial refresh
token comes from an OAuth flow the entry does not run, and Google's OAuth
2.0 Playground does it in a browser.

**Subscribed calendars** read a published `.ics` link — a timetable, a
fixture list, Proton Calendar's "share via link" — into the same vdir,
named by you and removable one at a time. Read-only, because that is what
vdirsyncer's `http` storage is. This is also the only way to reach
**Proton**, which speaks no CalDAV at all. A published link carries no
password, so anyone holding it can read that calendar; the entry says so
before writing one down.

Settings → **Mail** configures [`aerc`](https://aerc-mail.org)
(`pacman -S aerc`) against IMAP and SMTP. Both clients keep the credential
in the login keyring and read it back with a command, so neither config
file holds a secret. The aerc styleset is regenerated on every theme
switch, like the waybar colours.

**Outlook is not supported**, for mail or calendar: Microsoft retired
CalDAV for Outlook.com in favour of Graph, which nothing here speaks.

## Office documents

Nothing here opens a `.docx` out of the box — no suite, no viewer. A
deliberate floor: LibreOffice is 147 MB and looks nothing like the rest of
the desktop. Install `libreoffice-still` if you need Office formats to
round-trip faithfully; it is the only thing that really does.

Settings → **Web apps** installs Google Docs, Sheets and Slides, or
Microsoft 365, as real web apps: own window, own icon, launchable from
rofi. It needs `firefoxpwa` (`pacman -S firefoxpwa`) and downloads a
browser runtime of about 300 MB the first time, per user. We write those
manifests ourselves, because neither provider serves one to a logged-out
fetch — `docs.google.com/manifest.json` is a 404 and `office.com` answers
403 in an HTML body, so `firefoxpwa site install` against the page URL
fails outright.

`rclone` mounts Drive or OneDrive as a directory, which is the version of
"open it from the cloud" that does not involve publishing your document to
a public URL first — which is what both providers' *viewers* require,
since they take a URL and neither accepts a local file.

## Reading the screen: text, QR codes, and asking a model

`Print` opens screenshot mode. Beside `p` and `o`, which photograph:

| key | does | leaves the machine |
| --- | --- | --- |
| `t` | OCR the selected region onto the clipboard | no |
| `q` | decode a QR in the region onto the clipboard | no |
| `a` | ask a configured model about the region | **yes** |

`t` and `q` are local — `tesseract` and `zbar` run here.
`ASHLAROS_OCR_LANGS` selects OCR languages once the data is installed;
`eng` ships. The QR decode is restricted to QR symbologies, because dense
screen content otherwise false-positives as a barcode, and its result is
copied with `wl-copy --sensitive` and never shown: QR codes routinely
carry secrets, `otpauth://` URIs above all, and `cliphist` would otherwise
keep an unmarked entry.

**`a` is the one that sends your screen somewhere.** It hands the region
to [`aichat`](https://github.com/sigoden/aichat), an `optdepends` that is
not installed by default. Nothing is sent unless you press that key, and
nothing at all until you configure a provider — there is no default and no
bundled key. The notification names the model before the request goes out.

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
goes to that company — which is why this is a separate key, an optional
package, and unconfigured by default.

## AppImages

They run. `fuse2` and `fuse3` are installed, which is the whole
requirement: an AppImage is a self-mounting SquashFS, and without FUSE it
exits with `No suitable fusermount binary found on the $PATH` rather than
starting. Both are shipped because `fuse2` is deprecated upstream but is
what Type 2 images link, and those are still the majority.

Nothing integrates them into the launcher by itself — download, `chmod
+x`, run. [Gear Lever](https://gearlever.mijorus.it) is the current tool
for managing and updating them, distributed as a flatpak.

`flatpak` is installed but **no remote is configured**. Adding Flathub is
one command and is deliberately left to you: it is a third-party software
source, and enabling one without asking is not something an installer
should do.

```sh
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
```

The update badge already counts flatpak updates once you have some, and
`topgrade` updates them alongside everything else.

## Displays

`ashlaros-displays` (`Alt+d`, beside the scale keybinds) configures
displays: per-display scale, mode, rotation, VRR and enable/disable, plus
arrangement, order and the scaling globals.

**There are no profiles, deliberately.** way-displays has no such concept
and this does not invent one. Its model is declarative and reactive:
`cfg.yaml` describes what should be true for a set of connected displays,
and the daemon applies it whenever that set changes. Plugging the dock *is*
the switch, so "when I dock, use this layout" is a conditional rule rather
than a profile to select. Layering profiles on top would mean swapping the
file the daemon watches and writes, which is two sources of truth for one
config.

Every change goes through `way-displays --set/--delete/--toggle`, never by
writing YAML: the daemon stays the single writer, so there is no parser
here to drift and no fight over `--write`. Note that `--write` **destroys
comments and formatting** in `cfg.yaml` — hand-edits to that file are lost
the next time anything persists a change, whether from this tool or from
way-displays itself.

The one thing the CLI cannot express is a *conditional* rule, so the
lid-closed case prints the YAML block to add rather than writing it behind
the daemon's back and losing it at the next `--write`.

The three scale keybinds stay: a nudge is faster with a key than through a
menu, and they write through way-displays exactly as the TUI does.

## Snapshots, and what recovery actually involves

The default layout is btrfs, with `snapper` and `snap-pac` installed.
`snap-pac` is a pacman hook, so the snapshot exists *before* the upgrade
that broke things. `ashlaros-snapshot create` takes one on demand, `list`
shows what is there. Retention is 12, following package transactions
rather than the clock — snapper's own default keeps 50 and adds one hourly
forever, which fills a root subvolume quietly.

**Rollback is a rescue-media procedure, not a boot-menu one.** Omarchy
gets boot-menu rollback from limine; we boot with systemd-boot, which has
no equivalent of `limine-snapper-restore`.

**`snapper rollback` is not the command.** archinstall mounts `@` by
`subvol=` in fstab rather than as the filesystem's default subvolume, so
snapper cannot detect its ambit. Forcing it with `--ambit classic` is
worse than useless: it reports success, but fstab still wins at the next
boot, so the machine comes back **still broken** while the tool said it
recovered.

What works is replacing `@` itself. Verified end to end: a machine with a
deliberately destroyed `/etc/os-release` came back reading `AshlarOS` with
`$HOME` intact and a deleted binary restored.

1. Boot the AshlarOS ISO.
2. Unlock the disk — `cryptsetup open /dev/nvme0n1p2 root`. The
   passphrase, not the TPM: TPM enrolment is bound to PCR 7 and a firmware
   update can invalidate that keyslot.
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

`$HOME` survives, because `@home` is its own subvolume and only `@` is
replaced. `@log` and `@pkg` are separate for the same reason: the journal
recording the failure and the package cache holding the version you may
want to reinstall both outlive the rollback.

On an ext4 install none of this exists, and `ashlaros-snapshot` exits 127
saying so rather than failing — a tool that quietly does nothing turns "I
have no backups" into "I think I have backups".

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

`image/` builds a prebuilt disk image for the Pi 5. It is **not the ISO
for another architecture** — four of the ISO's defining properties cannot
exist on an ARM board:

| | x86_64 ISO | Pi 5 image |
| --- | --- | --- |
| kernel | `linux-cachyos` | `linux-rpi` (the board kernel) |
| userland | CachyOS `x86_64_v3` | plain Arch Linux ARM |
| boot | systemd-boot, UEFI | Pi firmware off a FAT partition |
| install | TUI installer, LUKS + TPM | written to a card, **unencrypted** |
| hardware detection | `chwd` | none (`chwd` is x86_64 only) |

What carries over is what a user sees: sway, `ashlaros-settings`, the
theming, the waybar config, the migrations mechanism.

With no installer to ask anything, setup happens on first boot
(`image/firstboot/`): grow the root filesystem, generate ssh host keys,
and create an account on tty1 **before the network comes up**. Arch Linux
ARM's `alarm` and `root` accounts are removed at build time and `sshd`
stays off until there is an account to reach — a prebuilt image with
published credentials on a network is the failure this avoids.

```sh
sudo ./image/build-image.sh out            # needs loop devices; aarch64 host
sudo ./image/test-image.sh out             # userland checks
```

`image/test-image.sh` boots the image for real: `mtools` pulls `linux-rpi`
and its DTB off the FAT partition with no loop device, and QEMU runs it
under `-M raspi4b` until the serial console shows userspace. The approach
is manjaro-sway's `ci/boot-smoke.sh`, which solved this first.

**It is still not proof it boots on a Pi 5.** QEMU has no `raspi5`
machine, so the image is booted on the Pi 4 model: that exercises the
kernel and root filesystem, not the Pi 5 firmware. It publishes on every
build to
[`latest/ashlaros-rpi5.img.xz`](https://ashlaros.download/iso/latest/ashlaros-rpi5.img.xz),
under its own alias and named for the board.

## Building

`mise.toml` pins the tooling — python, node, rust, ruff and uv — so a
workstation and a runner agree on versions, and `requirements.txt` pins the
two third-party packages the scripts import. `mise install` then
`mise run install` is the whole setup; `mise run lint` and `mise run test`
are what CI calls, so there is one definition of each rather than a copy in
every workflow.

Jobs that run inside an `archlinux` container are the exception and take
`python-boto3` from pacman: `repo-add` and `makepkg` have to come from the
same pacman generation that built the packages.

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

### Rebuilds when nothing in the package changed

A package compiled here records the sonames it linked against —
`libinput.so.10`, `libwlroots-0.19.so`. When the distribution moves one, our
package still installs, because pacman resolves the plain package names the
PKGBUILD declares, and then fails to start. Nothing in the package directory
changed, so nothing in the pipeline notices.

`.github/workflows/rebuild-on-breakage.yml` asks the published artefacts
directly, weekly and on both architectures: `scripts/audit_links.py`
downloads each package, reads every `DT_NEEDED` entry it ships, and resolves
it through `pacman -F` against the repositories as they are today. What no
longer resolves gets its `pkgrel` bumped by `scripts/bump_pkgrel.py` and
pushed straight to `main`.

The bump is what makes the rebuild possible at all, not bookkeeping:
`scripts/publish.py` refuses to replace an object the live database already
names — the worker serves packages as `immutable, max-age=31536000`, so a
reader mid-upload would get one build's package with another build's
signature — which means a rebuild at an unchanged version cannot be
published. There is deliberately no flag that forces one.

The bump is decimal, `6` to `6.1`, because `track-upstreams.yml` takes
upstream's PKGBUILD verbatim and the next upstream release resets `pkgrel` to
a small integer; `6.1` sorts above `6` and below `7`, so upstream always
wins. Authored packages are refused by the bumper — their `pkgrel` is the
commit count, so the commit recording a rebuild moves it already.

Unlike `track-upstreams.yml`, this pushes rather than opening a pull request:
taking an upstream change is a judgement call against our local edits, while
a `pkgrel` bump is one mechanical line gated on an audit that either found
broken links or did nothing.

### Where a package belongs

Three lists exist, and the boundary between them was decided ad hoc until
it was written down here.

`iso/packages.x86_64` is the **live** system: the installer plus a rescue
environment. It deliberately does not carry the desktop — `ashlaros-settings`
is absent, so the ISO installs sway, foot and firefox and nothing else of
the configured desktop, because pulling it in twice only makes the image
bigger.

`DESKTOP_PACKAGES` in `installer/orchestrator/phases_impl.py` is the
**installed** system: everything the desktop needs that is not implied by a
config file we ship.

`depends` in `packages/ashlaros-settings/PKGBUILD` is for a package **a
shipped config file references**. The shipped `.zshrc` sources fzf's key
bindings and initialises zoxide, so both are dependencies; `ripgrep` and
`bat` are not, because nothing we ship mentions them. The test is
mechanical: if removing the package would leave a config file pointing at
something absent, it is a dependency.

The reason for the split is `arch=any`: `ashlaros-settings` is installable
on ARM, so a dependency that only builds for x86_64 cannot go in it. That
is why `yay` is in `DESKTOP_PACKAGES` and only an optdepend here.

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
