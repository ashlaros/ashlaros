"""Phase state machine. Each phase is a (name, callable) pair; callables take
the InstallContext and either return cleanly or raise to abort the install."""

from __future__ import annotations

import json
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from .context import InstallContext
from .ui import error, info

PhaseFn = Callable[[InstallContext], None]

EXPECTED_PACKAGES_PATH = Path("/usr/share/ashlaros-installer/expected-packages")


class PhaseError(Exception):
    """Raised when a phase fails, wrapped with the phase name."""


def run(ctx: InstallContext, phases: list[tuple[str, PhaseFn]]) -> None:
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    state_path = ctx.state_dir / "state.json"
    state = {
        "started_at": time.time(),
        # the dashboard counts packages under <target>/var/lib/pacman/local;
        # publish the path rather than have the UI assume /mnt
        "target": str(ctx.target),
        "total_phases": len(phases),
        "current_index": 0,
        "current_phase": "Starting installation",
        "expected_packages": expected_package_count(),
        "phases": [],
    }
    write_state(state_path, state)

    for index, (name, fn) in enumerate(phases):
        state["current_index"] = index
        state["current_phase"] = name
        state["phase_started_at"] = time.time()
        write_state(state_path, state)

        info(f"› {name}")
        started = time.time()
        try:
            fn(ctx)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - started
            state["phases"].append(
                {"name": name, "status": "failed", "elapsed": elapsed, "error": str(exc)}
            )
            write_state(state_path, state)

            error(f"Phase '{name}' failed after {elapsed:.1f}s: {exc}")
            traceback.print_exc()
            raise PhaseError(f"phase {name} failed: {exc}") from exc

        elapsed = time.time() - started
        state["phases"].append({"name": name, "status": "ok", "elapsed": elapsed})
        write_state(state_path, state)

    state["current_index"] = max(len(phases) - 1, 0)
    state["current_phase"] = "Installation complete"
    state["finished_at"] = time.time()
    # expected against actual, so drift in the bar's denominator is visible
    # in an acceptance run rather than only by watching the bar creep
    state["installed_packages"] = installed_package_count(ctx.target)
    write_state(state_path, state)

    timing_path = ctx.target / "var" / "log" / "ashlaros-install-timing.json"
    timing_path.parent.mkdir(parents=True, exist_ok=True)
    write_state(timing_path, state)


def installed_package_count(target: Path) -> int:
    """Packages libalpm installed into the target - one directory each under
    var/lib/pacman/local, plus the ALPM_DB_VERSION file."""
    try:
        return sum(1 for entry in (target / "var/lib/pacman/local").iterdir() if entry.is_dir())
    except OSError:
        return 0


def expected_package_count() -> int:
    try:
        return int(EXPECTED_PACKAGES_PATH.read_text().strip())
    except (OSError, ValueError):
        return 0


def write_state(path: Path, state: dict) -> None:
    # the dashboard polls this while phases update it, so write atomically:
    # a reader must never observe a truncated document and reset its UI
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(path)
