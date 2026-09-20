"""How much of the progress bar each phase is worth.

Thirteen phases are not thirteen equal thirteenths. Measured on a real
install (TCG, no KVM, 954s, 778 packages), the shares are:

      2.1s   0.2%  Preparing the target
    738.3s  77.4%  Installing AshlarOS
      0.0s   0.0%  Configuring the system
      0.0s   0.0%  Enrolling the TPM
     49.6s   5.2%  Detecting hardware
      0.2s   0.0%  Configuring login
      2.1s   0.2%  Enabling services
      0.0s   0.0%  Resolving .local names
      4.9s   0.5%  Configuring the firewall
      0.5s   0.1%  Configuring snapshots
    156.3s  16.4%  Configuring the initramfs
      0.0s   0.0%  Locking the boot menu
      0.0s   0.0%  Validating boot

Three phases hold 99% of the wall clock and the other ten share 1%. Under
equal thirteenths the bar spent 77% of the install inside one cell of
forty and then walked the rest in the last minute, which reads as a hung
machine (#94).

The numbers are weights, not durations: only their ratio is used, so a
faster machine moves the bar at a different speed through the same
shape. KVM is roughly four times quicker overall but the work per phase
is the same work, and `Installing AshlarOS` dominates either way.

A floor of MIN_WEIGHT, because a phase worth 0.0s still has to be
visible: ten phases that each advance the bar by nothing are ten chances
for a user to watch a frozen screen, and the whole point here is that
something moves. It costs the long phases a few per mille.

Re-measure with `test/vm/run.sh collect-timing`, which reads the
orchestrator's own per-phase record off the live ISO before the reboot
discards it.
"""

from __future__ import annotations

# Seconds, from the run described above. Names must match build_phases().
MEASURED = {
    "Preparing the target": 2.1,
    "Installing AshlarOS": 738.3,
    "Configuring the system": 0.0,
    "Enrolling the TPM": 0.0,
    "Detecting hardware": 49.6,
    "Configuring login": 0.2,
    "Enabling services": 2.1,
    "Resolving .local names": 0.0,
    "Configuring the firewall": 4.9,
    "Configuring snapshots": 0.5,
    # Almost all of this is mkinitcpio, which still runs; only the splash
    # it used to configure is gone (#106).
    "Configuring the initramfs": 156.3,
    "Locking the boot menu": 0.0,
    "Validating boot": 0.0,
}

# What a phase is worth even when it measured zero. Two per mille is under
# a tenth of a cell at the bar's 40 columns, so it is not a lie about
# progress - it is the difference between a step that shows it happened
# and one that cannot.
MIN_WEIGHT = 2.0


def bands(names: list[str]) -> list[tuple[int, int]]:
    """The [floor, ceiling) per-mille span of each phase, in order.

    A phase the table does not know gets the mean of the ones it does,
    rather than zero: an unweighted phase is a phase someone just added,
    and giving it no width would freeze the bar exactly where the new work
    happens. Ratios only, so the spans always close on 1000 whatever the
    table sums to.
    """
    if not names:
        return []

    known = [MEASURED[name] for name in names if name in MEASURED]
    fallback = (sum(known) / len(known)) if known else MIN_WEIGHT
    weights = [max(MEASURED.get(name, fallback), MIN_WEIGHT) for name in names]

    total = sum(weights)
    spans = []
    running = 0.0
    for weight in weights:
        floor = running * 1000 / total
        running += weight
        # from the running total rather than by adding the last span, so
        # rounding cannot drift and the final ceiling is exactly 1000
        spans.append((round(floor), round(running * 1000 / total)))
    return spans
