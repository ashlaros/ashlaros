"""AshlarOS install orchestrator.

Owns the phase ordering, with archinstall used as a library subsystem rather
than as the top-level installer. The live-ISO wrapper turns its CLI flags
into ASHLAROS_INSTALL_* environment variables before python starts, so
archinstall's import-time argument parsing never sees flags of ours.
"""

from __future__ import annotations

import sys

from .context import InstallContext
from .phases import PhaseError, run
from .ui import error, info


def build_phases():
    """Phase order.

    enroll_tpm follows the bootloader, which is written inside
    install_system: it amends the crypttab that phase produced and rebuilds
    the initramfs around it, so it cannot precede either.
    """
    from .phases_impl import (
        configure_firewall,
        configure_login,
        configure_mdns,
        configure_system,
        enable_services,
        enroll_tpm,
        install_system,
        prepare_live,
        run_hardware_detection,
        validate_boot,
    )

    return [
        ("Preparing the target", prepare_live),
        ("Installing AshlarOS", install_system),
        ("Configuring the system", configure_system),
        ("Enrolling the TPM", enroll_tpm),
        ("Detecting hardware", run_hardware_detection),
        ("Configuring login", configure_login),
        ("Enabling services", enable_services),
        ("Resolving .local names", configure_mdns),
        ("Configuring the firewall", configure_firewall),
        ("Validating boot", validate_boot),
    ]


def main() -> int:
    try:
        ctx = InstallContext.from_env()
    except RuntimeError as exc:
        error(f"Configuration error: {exc}")
        return 2

    info(f"Installing AshlarOS for {ctx.username} → {ctx.target}")

    try:
        run(ctx, build_phases())
    except PhaseError:
        error("Installation halted.")
        return 1
    except KeyboardInterrupt:
        error("Installation interrupted.")
        return 130

    info("Installation complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
