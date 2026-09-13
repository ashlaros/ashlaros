# The VM harness

Boots an AshlarOS ISO under QEMU, drives the installer through its four
screens, and lets you type commands on the installed system and take
pictures of the result.

It exists because the things worth checking are only observable at
runtime. The ISO boots UEFI-only with systemd-boot, the installer is a gum
TUI, the desktop is sway — none of that is testable by reading files, and
several real bugs (a broken `archinstall` import, a target that kept
Arch's `os-release`, a keymap that reached the console but not the
desktop) were invisible until something booted.

## Use

```sh
test/vm/run.sh fetch              # newest published ISO, or: fetch 2026.09.11
test/vm/run.sh install            # boot it and drive the installer
test/vm/run.sh boot               # later: boot the disk it installed to
test/vm/run.sh shot desktop       # screenshot -> $WORKSPACE/out/desktop.png
test/vm/run.sh de 'pacman -Q sway' q   # run a command on the installed system
test/vm/run.sh clean              # throw the workspace away
```

`install` takes about 35 minutes. There is no KVM inside the container
even with `/dev/kvm` mapped, so this is TCG.

The workspace defaults to `/tmp/ashlaros-vm` and holds the ISO, the target
disk, the firmware variables and `out/`. Set `WORKSPACE` to keep several.

`TPM=no` installs without a TPM, which is the passphrase-at-every-boot
path. `LID=yes` attaches an ACPI lid button, reporting closed.

The lid is worth explaining: QEMU has no lid device — `-device help` lists
none — so the hardware predicates' positive lid path had never run against
anything but a fabricated sysfs tree. A lid is defined by an ACPI table
rather than by a device model, so `boot.sh` compiles a four-line SSDT with
`iasl` and loads it with `-acpitable`. The guest kernel's own button
driver then creates `/proc/acpi/button/lid/LID0/state`, which is the file
`laptop` and `laptop-closed` actually read.

## Two things that will bite you

**Keyboard layouts.** QMP sends key *positions*, not characters, so what
arrives depends on the keymap the guest has loaded. The live ISO is
US-positioned; an installed system runs whatever the installer configured,
`de` by default. That is why there are two tables in `qmp.py` and why
`run.sh` has both `run` (live) and `de` (installed). Get it wrong and
`swaymsg -t get_inputs` arrives as `swazmsg ßt get?inputs` — which is
itself how the keymap bug in #14 was first confirmed.

Uppercase letters and most punctuation work; a few characters have no
mapping at all, so prefer commands that avoid them. `|`, `"` and `$?` are
the usual casualties.

**Do not kill qemu at the "Reboot?" prompt.** The ESP is still in the
qcow2 writeback cache, and the next boot reports `Volume corrupt`, which
looks like a bootloader bug and is not one. `install.py` takes the offered
reboot for exactly this reason.

## How it hangs together

| file | what |
| --- | --- |
| `Dockerfile` | qemu, OVMF, swtpm, python |
| `boot.sh` | runs inside the container; `TPM=no` and `CDROM=no` switch the two interesting variants |
| `qmp.py` | the QMP client: keys in, screenshots out |
| `install.py` | drives the installer, Enter through every default |
| `run.sh` | the front end; the only file you normally call |

`run.sh film <name> [count] [gap]` samples the framebuffer on a loop.
One `shot` cannot catch anything that moves: the entry animation runs for
under a second before the configurator draws over it, so by the time a
single screenshot is asked for, only the settled screen is left.

Screenshots are PPM from qemu, converted to PNG by `run.sh` with nothing
but the standard library — the container has no Pillow and does not need
it.

`run.sh install` waits for the installer to actually be on screen before
typing. It detects it by the logo block, because "something is being
drawn" is also true of the boot menu, and a driver that starts too early
types into a void and leaves the installer sitting on screen 1.

## Variants worth running

- `TPM=no test/vm/run.sh boot` — the machine without a TPM. The install
  must complete and leave passphrase unlock, with no error.
- `CDROM=no test/vm/run.sh boot` — boots the installed disk. With a TPM
  attached and enrolled, this must reach the desktop with no passphrase
  prompt.
