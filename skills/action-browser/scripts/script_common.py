from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


DEFAULT_TAB = ""


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def unwrap_eval(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return value


def parse_json_output(output: str) -> Any:
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output


def run_command(
    command: Sequence[str],
    *,
    timeout: float = 30.0,
    check: bool = True,
    cwd: Path | None = None,
) -> str:
    result = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if check and result.returncode != 0:
        raise RuntimeError(output or f"command failed: {' '.join(command)}")
    return output


def add_session_tab_args(
    parser: argparse.ArgumentParser,
    *,
    default_session: str,
    session_help: str = "ActionBook session id",
    tab_help: str = "ActionBook tab id; auto-detect when omitted",
) -> None:
    parser.add_argument("--session", default=default_session, help=session_help)
    parser.add_argument("--tab", default=DEFAULT_TAB, help=tab_help)
