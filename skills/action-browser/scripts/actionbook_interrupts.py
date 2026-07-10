"""Shared interrupt handling for ActionBook workflow scripts."""

from __future__ import annotations

import signal
import sys
import time
from typing import Any


_INTERRUPTED = False


def _handle_interrupt(signum: int, _frame: Any) -> None:
    global _INTERRUPTED
    _INTERRUPTED = True
    name = signal.Signals(signum).name
    print(f"Interrupted by {name}", file=sys.stderr, flush=True)
    raise KeyboardInterrupt


def install_interrupt_handlers() -> None:
    """Map SIGINT and SIGTERM to KeyboardInterrupt for uniform exit code 130."""
    signal.signal(signal.SIGINT, _handle_interrupt)
    signal.signal(signal.SIGTERM, _handle_interrupt)


def is_interrupted() -> bool:
    return _INTERRUPTED


def check_interrupt() -> None:
    if _INTERRUPTED:
        raise KeyboardInterrupt


def interruptible_sleep(seconds: float) -> None:
    check_interrupt()
    time.sleep(seconds)
    check_interrupt()
