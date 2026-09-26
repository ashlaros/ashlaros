# Contributing

How AshlarOS is built and published. The [README](README.md) is for people
running it; this is for people changing it.

One repository holds everything:

```
packages/     PKGBUILDs published to the ashlaros pacman repository
iso/          the archiso profile the ISO is built from
installer/    the gum TUI installer shipped on the ISO
image/        the prebuilt Raspberry Pi 5 disk image
branding/     logo, favicon, background, palette, the mark as a font glyph
screenshots/  the headless capture that photographs the desktop
worker/       cloudflare worker serving the repository and the ISOs from R2
scripts/      publish tooling for the repository
test/vm/      boots a published ISO under QEMU and drives the installer
```

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

x86_64 builds use CachyOS's v3 compiler flags, copied from CachyOS's
`docker-makepkg-v3` into a `makepkg.conf.d` drop-in by
`.github/scripts/prepare-container.sh`: `-march=x86-64-v3 -O3`, LTO,
`target-cpu=x86-64-v3` for Rust and `GOAMD64=v3` for Go. aarch64 keeps Arch
Linux ARM's defaults. The drop-in is not part of any package's source hash,
so a flag change reaches a package at its next rebuild, not at once.

An installed system builds locally (yay, makepkg) with CachyOS's own
`/etc/makepkg.conf`, from CachyOS's `pacman`: the same flags with
`-march=native` and `target-cpu=native`, which beat v3 on the machine that
runs the result. `ashlaros-settings` adds only what that file lacks, in
`/etc/makepkg.conf.d/zz-ashlaros.conf`: `GOAMD64=v3` and Rust's packed
relocations.

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
aarch64, an aarch64 compile patch added — so that merge is three-way against
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
names — a package is redirected to the bucket's own hostname and cached
there for a year, so a reader mid-upload would get one build's package with
another build's signature — which means a rebuild at an unchanged version
cannot be published. There is deliberately no flag that forces one.

The bump is decimal, `6` to `6.1`, because `track-upstreams.yml` takes
upstream's PKGBUILD verbatim and the next upstream release resets `pkgrel` to
a small integer; `6.1` sorts above `6` and below `7`, so upstream always
wins. Authored packages are refused by the bumper — their `pkgrel` is the
commit count, so the commit recording a rebuild moves it already.

Unlike `track-upstreams.yml`, this pushes rather than opening a pull request:
taking an upstream change is a judgement call against our local edits, while
a `pkgrel` bump is one mechanical line gated on an audit that either found
broken links or did nothing.

### Dropping a package

Delete its directory, its `packages/.upstream/` merge base and its
`upstreams.yml` entry, and push. `publish.py` only adds to the
repository, so the next `build-packages.yml` run's `remove-dropped` job
takes out what the tree no longer builds: `scripts/remove_dropped.py`
compares each live database with every `pkgname` the PKGBUILDs produce,
removes the leftovers with `repo-remove`, uploads the database, and only
then deletes the files, so nothing a client can fetch names a missing one.
Before this, dropped packages stayed installable by name for good; nine had
built up in each tree by 2026-09-26.

It refuses the whole run, rather than removing part of it, when a package
still published depends on a dropped one that no repository on that
architecture offers: Arch's for x86_64, Arch Linux ARM's for aarch64. A
dependency another repository satisfies only changes which package pacman
picks. It also refuses more than 20 removals at once, which is a misread
tree rather than a drop. Run it without `--apply` to see what it would
take out.

### Where a package belongs

Three lists exist, and the boundary between them was decided ad hoc until
it was written down here.

`iso/packages.x86_64` is the **live** system: the installer plus a rescue
environment. It deliberately does not carry the desktop — `ashlaros-settings`
is absent, so the ISO installs sway, foot and firefox and nothing else of
the configured desktop, because pulling it in twice only makes the image
bigger.

What an install asks pacman for comes from three places - the
configurator's `packages`, `DESKTOP_PACKAGES`, and `base` - and
`scripts/seed_install_cache.py` stages all three on the medium, so an
install needs no network. `requested_packages()` is the one list;
`check_iso_packages.py` checks the staged cache against it, so a package
added to any of the three and not staged fails the ISO build rather than
the first offline install.

The configurator's packages and `DESKTOP_PACKAGES` go to pacman as one
transaction, and that has to stay true. The stage resolves them together,
and pacman picks a provider for a virtual dependency by what else is in the
same transaction: split in two, the first half chose
`pulse-native-provider` for `pulsemixer` where the desktop's
`pipewire-pulse` would do, and that package was never staged.

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
