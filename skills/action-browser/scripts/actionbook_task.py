#!/usr/bin/env python3
"""Run one browser workflow inside an atomic task-tab lifecycle."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.actionbook_session import DEFAULT_SESSION, acquire_task_tab, release_task_tab


def normalize_command(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("missing workflow command after --")
    return command


def run_task(args: argparse.Namespace) -> int:
    command = normalize_command(args.command)
    record = acquire_task_tab(
        argparse.Namespace(
            task=args.task,
            session=args.session,
            url=args.url,
            adopt_running_session=args.adopt_running_session,
            allow_visible_recovery=not args.no_visible_recovery,
        )
    )
    env = os.environ.copy()
    env.update(
        {
            "ACTIONBOOK_TASK_ID": str(record["task_id"]),
            "ACTIONBOOK_SESSION_ID": str(record["session_id"]),
            "ACTIONBOOK_TAB_ID": str(record["tab_id"]),
        }
    )
    exit_code = 1
    try:
        result = subprocess.run(
            command,
            cwd=str(Path(args.cwd).expanduser()) if args.cwd else None,
            env=env,
            check=False,
        )
        exit_code = int(result.returncode)
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        try:
            release_task_tab(argparse.Namespace(task=args.task))
        except Exception as exc:  # noqa: BLE001
            print(f"ActionBook task-tab cleanup failed: {exc}", file=sys.stderr)
            if exit_code == 0:
                exit_code = 1
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Acquire one owned ActionBook tab, run a workflow, then release the tab in the same process."
    )
    parser.add_argument("--task", required=True, help="Stable task id")
    parser.add_argument("--session", default=DEFAULT_SESSION, help="Preferred ActionBook session id")
    parser.add_argument("--url", default="about:blank", help="Initial URL for the owned tab")
    parser.add_argument("--cwd", default="", help="Working directory for the workflow command")
    parser.add_argument(
        "--adopt-running-session",
        action="store_true",
        help="Allow adoption of another healthy extension session when the named session is unavailable",
    )
    parser.add_argument(
        "--no-visible-recovery",
        action="store_true",
        help="Do not cold-start Chrome or create a browser window",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Workflow command after --")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run_task(args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
