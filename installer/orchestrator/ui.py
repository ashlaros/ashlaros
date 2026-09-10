"""Progress output. The dashboard tails this on the live TTY, so every line
is flushed as it is written rather than buffered until exit."""

from __future__ import annotations

import sys


def info(message: str) -> None:
    print(message, flush=True)


def error(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
