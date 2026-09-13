# AshlarOS

An Arch-based distribution: plain Arch underneath, [CachyOS](https://cachyos.org)
v3-optimised repositories layered over it, `chwd` for hardware detection,
`linux-cachyos` as the kernel, systemd-boot, and a sway desktop carried over
from [manjaro-sway](https://github.com/manjaro-sway/manjaro-sway).

![The AshlarOS desktop](https://iso.ashlaros.download/latest/screenshots/desktop.png)

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

### Installs made before 2026-09-11 need one rename for the theme toggle

The theme switcher shipped with the sway config named its stashed theme
`theme.night.conf_`, while the toggle that reads it looked for
`theme.light.conf_`. The two never met, so the waybar theme module never
appeared at all. Both halves say `light` now.

A fresh install is correct. An existing one keeps the old name in `$HOME`,
where no package upgrade will touch it — nothing here rummages through home
directories. Two renames fix it:

```sh
cd ~/.config
mv sway/definitions.d/theme.night.conf_ sway/definitions.d/theme.light.conf_
mv foot/foot-theme.night.ini_ foot/foot-theme.light.ini_
cp foot/foot-theme.ini foot/foot-theme.dark.ini_
```

The third line is not a typo: `foot-theme.ini` is generated from a
`.dark.` and a `.light.` half rather than being one of them, so the dark
half has to exist before the first toggle can merge anything. `skel`
rewrites all of this from the shipped defaults if you would rather start
clean — it backs up `~/.config` first.

## Screenshots

`screenshots/` photographs the desktop and publishes to
[`iso.ashlaros.download/latest/screenshots/`](https://iso.ashlaros.download/latest/screenshots/desktop.png),
which is what the picture above and the landing page point at. They are not
committed: a handful of PNGs regenerated on every settings change is a
repository that grows forever for files nobody diffs.

A shot of the booted ISO would show bare sway. `iso/packages.x86_64` installs
`sway`, `foot` and `firefox` and deliberately leaves `ashlaros-settings` out,
because the live system is the installer plus a rescue environment. So the
capture installs the settings package from the published repository into a
container and runs sway on wlroots' headless backend, which draws a full
session with no GPU and no seat. Seconds, no nested virtualisation, and it
renders the real configured desktop.

What it is not: proof that anything boots or installs. It is a picture of the
desktop, and the ISO build has its own checks for the other question.

`screenshots/record.sh` records a short silent tour beside the stills,
published at
[`latest/video/tour.webm`](https://iso.ashlaros.download/latest/video/tour.webm)
and shown on the download page. A still cannot show tiling, a launcher
opening or the theme switching; thirty seconds can. The session setup is
`screenshots/session.sh`, shared with the capture script rather than copied
into it — the D-Bus re-exec and the waybar workaround are the hard-won part
and two copies would drift.

It is silent (a container has no audio, and silence means no narration to
maintain), and the theme scene shows **the bar switching**: measured, a
toggle repaints waybar by 79% while terminal panes change by under 14%,
because foot takes its colours from the server that started before the
switch. That is what the desktop really does, so that is what the tour
shows.

`screenshots/shots.yaml` is one entry per picture - the commands to run, the
`swaymsg` placement between them, and how long to let it settle. Adding a
picture is a block there rather than another `if` in a script.

Publishing is only under `latest/screenshots/`. The desktop changes when
`packages/ashlaros-settings/payload/` changes, which is decoupled from the
ISO build, so writing these under `<version>/screenshots/` would say "this is
what that ISO looked like" while meaning "what the desktop looked like
whenever this last ran".

Consecutive runs differ - the bar shows a clock, the weather, and a pending
update count. That is fine for publishing and fatal for diffing, so there is
deliberately no "screenshots changed" check. These are pictures, not golden
files.

## The games

[`ashlaros.download/game/`](https://ashlaros.download/game/) is **Courses**,
a falling-block game, and [`/game/quarry`](https://ashlaros.download/game/quarry)
is **Quarry**, a block breaker. Both have a daily leaderboard. Everyone gets the same pieces
on the same day, so the board compares play rather than luck.

**The worker issues a seed, the game runs locally, the worker verifies the
replay.** The design is `boredland/slopduel`'s `GAME-RULES.md`, whose
failure modes were all found the expensive way there:

- **The seed is the only source of world state**, and `Math.random()`
  appears nowhere in the simulation — not "only for visuals", nowhere.
- **Time is a tick index, never a wall clock.** The simulation is discrete,
  so a timestamp would be a lossier way of naming the same integer. A
  suspended tab owes the simulation nothing, so there is no late timestamp
  to reject and no tolerance to tune — which is the bug that lost someone a
  duel upstream for taking a phone call.
- **The replay is the submission.** The server recomputes the score and
  discards the number the client reported; the seed comes from the server's
  record, never from the request.
- **One attempt per seed, enforced server-side** by a unique index. The
  board is a pure function of the seed, so a player who restarts gets the
  same board now known — measured upstream at +34.7% for best-of-five.
- **A run belongs to the day its seed was issued**, not the moment it was
  submitted: a run started at 23:59 and submitted at 00:01 was played on
  yesterday's pieces, and scoring it against today's seed would reject an
  honest player for starting late.
- **Integers only.** Two engines agreeing on integer arithmetic is a
  property of the arithmetic; agreeing on floats is a hope.

**Identity is three characters, the way Atari did it.** A leaderboard needs
a stable name, there are no accounts, and `geo.js` commits this project to
storing nothing identifying. `[A-Z0-9]`×3 is 46,656 possibilities — enough
to feel personal, far too short to be a moderation queue — and entering
them after a run that placed is the arcade ritual rather than a form.
Collisions are fine; the arcade never cared either.

**Two boards.** The daily one is the competition and resets, so a newcomer
is never looking at a wall of scores set months ago. All-time is one row
per player rather than the best runs — scores from different seeds are not
comparable, so a table of runs would rank the kindest seed — with a rolling
30-day window beside it, because an all-time table ossifies. Every run is
kept and the boards are queries over them, so a rating (which would remove
seed luck properly) can be added later without a backfill.

**Offline is the default.** Without the network the game still plays, on a
seed derived by the same function the server uses — imported, not rewritten
— so an offline run is on the same board as everyone else's that day. Only
the leaderboard needs a connection.

**Quarry** is the Arkanoid formula rather than 1976 Breakout: designed
seeded walls, multi-hit and indestructible bricks, falling capsules and
multi-ball. Two of its constants are measurements rather than taste, and
`worker/test/quarry-balance.mjs` is what took them:

- **The paddle is faster than the ball.** At `px(4)` every skill band lost
  inside nine seconds — the ball crosses the field in 40 ticks where the
  paddle needed 60, and no skill closes a gap the paddle cannot physically
  close.
- **The wall is sized to the measured clear rate.** A perfect tracker
  breaks 0.46 bricks/second, so an eight-row wall needing 137 hits was
  195 seconds of work inside a 120-second run — nobody ever cleared a
  level and the level bonus was unreachable code. That is `slop-out`'s
  finding reproduced almost exactly (they measured 0.56 against 0.93).

The harness reports the score spread and how runs end for four scripted
skill bands; run it before changing a constant, because none of the above
is visible from reading the code:

```sh
cd worker && node test/quarry-balance.mjs 12
```

**The replay logs the paddle's target, never its position.** The paddle
closes on the target at a fixed speed, so the server derives where it
went rather than being told — and the speed cap is a verification
requirement, not a difficulty choice: uncapped, every position at every
tick is legal and the verifier has nothing to reject. Sampled targets are
12 events/second against 60 for logging every tick.

`worker/src/game/logic.js` is the single implementation: the page imports it
to play and the verifier imports it to replay. `docs/game/logic.js` is
generated from it by `npm run game:sync`, which `npm test` and the deploy
both run — a hand-maintained second copy of a simulation is exactly the
drift that would reject every honest score.

Verification runs in a **Durable Object**, not the fetch handler. The free
plan gives a handler 10 ms of CPU and re-stepping a multi-minute run at
60 Hz does not fit; `waitUntil` draws on the same budget and so does a
scheduled handler. A Durable Object gets 30 s per invocation, and a handler
waiting on one spends no CPU of its own.

## Download stats

`iso.ashlaros.download/stats` counts ISO downloads, and `/stats.json` is the
same data machine-readable. A download is one whole-image `GET` that
returned `200`: a resumed download issues many range requests and would
otherwise report one image as dozens, a revalidation transfers nothing, and
`SHA256SUMS` is not a download. Only the ISO site counts — every
`pacman -Sy` is a database fetch, and that volume would drown the signal.

Images taken from `/latest/` carry no version in their URL, so they are
counted as their own row rather than attributed to whichever image happened
to be newest. That number is worth having on its own: it is how many people
take the current image without pinning one.

Two stores, because neither works alone. Analytics engine takes the writes —
`writeDataPoint` is non-blocking, so counting costs a download nothing — but
retains three months. KV keeps the archive indefinitely, written once a
month by a cron on the 2nd rather than per download: KV allows one write per
second per key and propagates for up to a minute, so a per-download counter
would lose counts to last-write-wins. The 2nd rather than the 1st because
ingestion is not instant, and a closed month's last events have to be
queryable before the month is archived.

Writing needs no credentials; reading does. Analytics engine has no query
binding, so the page reads over the SQL API with a token
(`wrangler secret put ANALYTICS_TOKEN`, scoped *Account · Account Analytics ·
Read*). That asymmetry is deliberate: downloads are counted whether or not
the token is set, and it can be added later without losing anything already
counted. Until it is, the page says so rather than answering 500.

## Settings

`ashlaros-settings-tui` (`Super+,`) is one entry point for the settings
that are otherwise commands you have to know: locale and keyboard layout,
time and timezone, kernel variants from the cachyos repository, and chwd's
hardware profiles. Displays and package installation dispatch to
`ashlaros-displays` and `pacseek`.

**A launcher, not a control panel.** Every entry either runs an existing
tool or collects input and runs one command; the menu owns no settings
logic. An entry whose binary is not installed is absent rather than
present and broken.

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

The default layout is btrfs, and `snapper` plus `snap-pac` are installed
with it. `snap-pac` is a pacman hook, so every transaction is bracketed by
a snapshot without anyone remembering to ask for one: the snapshot exists
*before* the upgrade that broke things. `ashlaros-snapshot create` takes
one on demand, `ashlaros-snapshot list` shows what is there.

**Rollback is a rescue-media procedure, not a boot-menu one.** Omarchy gets
boot-menu rollback from limine; we boot with systemd-boot, which has no
equivalent of `limine-snapper-restore`.

**`snapper rollback` is not the command.** It was tried on a real install
and does not work on this layout: archinstall mounts `@` by `subvol=` in
fstab rather than by setting it as the filesystem's default subvolume, so
snapper reports *"Cannot detect ambit since default subvolume is unknown"*.
Forcing it with `--ambit classic` is worse than useless — it reports
success and sets the default subvolume, but fstab's `subvol=/@` still wins
at the next boot, so the machine comes back **still broken** while the tool
said it recovered.

What works is replacing `@` itself. Verified end to end: a machine with a
deliberately destroyed `/etc/os-release` came back reading `AshlarOS` with
`$HOME` intact and a deleted binary restored.

1. Boot the AshlarOS ISO.
2. Unlock the disk — `cryptsetup open /dev/nvme0n1p2 root`. The passphrase,
   not the TPM: TPM enrolment is bound to PCR 7 and a firmware update can
   invalidate that keyslot, so the passphrase is the one credential that
   always works.
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

5. Reboot. Delete `@.broken` later with
   `btrfs subvolume delete /mnt/@.broken` once the machine is known good —
   it costs nothing until the snapshots inside it diverge.

`$HOME` survives a root rollback, because `@home` is its own subvolume and
only `@` is replaced. `@log` and `@pkg` are separate for the same reason —
the journal that records the failure, and the package cache holding the
version you may want to reinstall, both outlive the rollback.

Retention is 12 snapshots with no timeline: snapshots follow package
transactions, not the clock. Snapper's own default keeps 50 and adds one
every hour forever, which fills a root subvolume quietly.

On an ext4 install none of this exists, and `ashlaros-snapshot` says so and
exits 127 rather than failing — an update path can tell "cannot snapshot
here" from "tried and failed". A snapshot tool that quietly does nothing is
worse than no snapshot tool, because it turns "I have no backups" into "I
think I have backups".

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
  ARM kernel or v3 userland to build one from. There is a Raspberry Pi 5
  *disk image* instead - a different thing, described below.

## The Raspberry Pi 5 image

`image/` builds a prebuilt disk image for the Pi 5. It is **not the ISO for
another architecture** - four of the ISO's defining properties cannot exist
on an ARM board, and pretending otherwise would mis-sell it:

| | x86_64 ISO | Pi 5 image |
| --- | --- | --- |
| kernel | `linux-cachyos` | `linux-rpi` (the board kernel) |
| userland | CachyOS `x86_64_v3` | plain Arch Linux ARM |
| boot | systemd-boot, UEFI | Pi firmware off a FAT partition |
| install | TUI installer, LUKS + TPM | written to a card, **unencrypted** |
| hardware detection | `chwd` | none (`chwd` is x86_64 only) |

What does carry over is what a user actually sees: sway, `ashlaros-settings`,
the theming, the waybar config, the migrations mechanism.

Because there is no installer to ask anything, the image does its setup on
first boot (`image/firstboot/`): it grows the root filesystem to fill the
card, generates ssh host keys for that machine, and creates an account on
tty1 **before the network comes up**. Arch Linux ARM's `alarm`/`alarm` and
`root`/`root` accounts are removed at build time and `sshd` stays off until
there is an account to reach - a prebuilt image with published credentials
on a network is the failure this is built to avoid.

```sh
sudo ./image/build-image.sh out            # needs loop devices; aarch64 host
sudo ./image/test-image.sh out             # userland checks
```

`image/test-image.sh` boots the image for real: `mtools` pulls `linux-rpi`
and its DTB off the FAT partition with no loop device, and QEMU runs it
under `-M raspi4b` until the serial console shows userspace. The approach
is manjaro-sway's `ci/boot-smoke.sh`, which solved this first.

**It is still not a proof it boots on a Pi 5.** QEMU has no `raspi5`
machine, so the image is booted on the Pi 4 model: that exercises the
kernel and the root filesystem, not the Pi 5 firmware. Publishing is a
manual, opt-in input on `build-image.yml` and should follow someone
writing the artefact to a card.

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
