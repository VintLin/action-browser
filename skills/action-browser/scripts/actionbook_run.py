#!/usr/bin/env python3
"""Run and stop long ActionBook skill workflows by run id.

This wrapper exists because interrupting an agent turn does not always stop
the local process launched by a skill. It starts the child command in
its own process group, writes a durable run state file, and provides a stop
command that can terminate the whole process group later.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.scheduler_lib import utc_now


RUNS_DIR = Path.home() / ".action-browser" / "runs"
RUNNING_STATUS = "running"
STALE_STATUS = "stale"
TERMINAL_STATUSES = {"exited", "failed", "stopped", "stale"}
DEFAULT_HEARTBEAT_INTERVAL = 10.0
DEFAULT_HEARTBEAT_STALE_SECONDS = 60.0


def state_path(run_id: str, runs_dir: Path) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in run_id).strip("._-")
    if not safe:
        raise ValueError("run id is empty after sanitization")
    return runs_dir / f"{safe}.json"


def monitor_path(path: Path, suffix: str) -> Path:
    return path.with_suffix(f".{suffix}")


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return {"run_id": path.stem, "status": "invalid", "state_file": str(path)}
    return data if isinstance(data, dict) else {"run_id": path.stem, "status": "invalid", "state_file": str(path)}


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utc_now()
    state["state_file"] = str(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    monitor_path(path, "status").write_text(
        f"{str(state.get('status') or 'unknown').upper()}\n",
        encoding="utf-8",
    )


def touch_heartbeat(path: Path) -> None:
    heartbeat = monitor_path(path, "heartbeat")
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    heartbeat.touch()


def sync_progress(path: Path, state: dict[str, Any]) -> None:
    progress_file = str(state.get("progress_file") or "").strip()
    if not progress_file:
        return
    progress_path = Path(progress_file).expanduser()
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(progress, dict):
        return
    state["progress_file"] = str(progress_path)
    state["last_progress_at"] = progress.get("last_progress_at") or progress.get("updated_at")
    state["current_item"] = progress.get("current_item") or progress.get("current_post")
    state["current_post"] = progress.get("current_post") or progress.get("current_item")
    state["last_stage"] = progress.get("stage") or progress.get("last_stage")
    state["last_observed_url"] = progress.get("last_observed_url") or progress.get("current_url")
    state["completed_items"] = progress.get("completed_items")
    state["requested_items"] = progress.get("requested_items")
    state["progress_status"] = progress.get("status")


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def refresh_state(path: Path, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    current = state or load_state(path)
    if not current:
        return None
    pid = int(current.get("pid") or 0)
    if str(current.get("status") or "") == RUNNING_STATUS and not process_alive(pid):
        current["status"] = STALE_STATUS
        current["exit_code"] = None
        write_state(path, current)
    elif str(current.get("status") or "") == RUNNING_STATUS:
        heartbeat_path = Path(
            str(current.get("heartbeat_file") or monitor_path(path, "heartbeat"))
        ).expanduser()
        stale_after = float(current.get("heartbeat_stale_seconds") or DEFAULT_HEARTBEAT_STALE_SECONDS)
        try:
            heartbeat_stale = heartbeat_path.exists() and time.time() - heartbeat_path.stat().st_mtime > stale_after
        except OSError:
            heartbeat_stale = False
        if heartbeat_stale:
            current["status"] = STALE_STATUS
            current["stale_reason"] = "heartbeat_expired"
            current["exit_code"] = None
            write_state(path, current)
    return current


def running_state(path: Path) -> dict[str, Any] | None:
    state = refresh_state(path)
    if state and str(state.get("status") or "") == RUNNING_STATUS:
        return state
    return None


def normalize_command(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("missing command after --")
    return command


def terminate_group(pgid: int, grace_seconds: float) -> str:
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return "not_found"
    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return "terminated"
        except PermissionError:
            time.sleep(0.2)
            continue
        time.sleep(0.2)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return "terminated"
    except PermissionError:
        return "permission_denied"
    return "killed"


def run_command_cli(args: argparse.Namespace) -> int:
    if float(args.heartbeat_interval) <= 0:
        raise ValueError("heartbeat interval must be greater than 0")
    if float(args.heartbeat_stale_seconds) <= 0:
        raise ValueError("heartbeat stale seconds must be greater than 0")
    runs_dir = Path(args.runs_dir).expanduser()
    path = state_path(args.id, runs_dir)
    existing = running_state(path)
    if existing and not args.replace:
        print(f"run already active: {args.id} pid={existing.get('pid')} pgid={existing.get('pgid')}", file=sys.stderr)
        return 2
    if existing and args.replace:
        terminate_group(int(existing.get("pgid") or existing.get("pid") or 0), args.grace)

    command = normalize_command(args.command)
    cwd = str(Path(args.cwd).expanduser()) if args.cwd else os.getcwd()
    state: dict[str, Any] = {
        "run_id": args.id,
        "status": "starting",
        "command": command,
        "cwd": cwd,
        "started_at": utc_now(),
        "pid": None,
        "pgid": None,
        "exit_code": None,
        "progress_file": str(Path(args.progress_file).expanduser()) if args.progress_file else "",
        "heartbeat_interval_seconds": float(args.heartbeat_interval),
        "heartbeat_stale_seconds": float(args.heartbeat_stale_seconds),
        "heartbeat_file": str(monitor_path(path, "heartbeat")),
        "pid_file": str(monitor_path(path, "pid")),
        "status_file": str(monitor_path(path, "status")),
        "last_heartbeat_at": None,
        "last_progress_at": None,
        "current_item": None,
        "current_post": None,
    }
    write_state(path, state)

    try:
        proc = subprocess.Popen(command, cwd=cwd, start_new_session=True)
    except OSError as exc:
        state["status"] = "failed"
        state["error"] = str(exc)
        state["exit_code"] = 127
        write_state(path, state)
        raise
    state["status"] = "running"
    state["pid"] = proc.pid
    state["pgid"] = os.getpgid(proc.pid)
    monitor_path(path, "pid").write_text(f"{proc.pid}\n", encoding="utf-8")
    touch_heartbeat(path)
    state["last_heartbeat_at"] = utc_now()
    sync_progress(path, state)
    write_state(path, state)

    stopping = {"active": False}

    def handle_signal(signum: int, _frame: Any) -> None:
        if stopping["active"]:
            return
        stopping["active"] = True
        state["status"] = "stopping"
        state["signal"] = signal.Signals(signum).name
        write_state(path, state)
        terminate_group(int(state["pgid"]), args.grace)

    old_int = signal.signal(signal.SIGINT, handle_signal)
    old_term = signal.signal(signal.SIGTERM, handle_signal)
    try:
        last_heartbeat = time.monotonic()
        while True:
            code = proc.poll()
            if code is not None:
                touch_heartbeat(path)
                state["last_heartbeat_at"] = utc_now()
                sync_progress(path, state)
                state["exit_code"] = code
                if stopping["active"] or code in (-signal.SIGINT, -signal.SIGTERM, -signal.SIGKILL, 130, 143):
                    state["status"] = "stopped"
                    wrapper_code = 130
                elif code == 0:
                    state["status"] = "exited"
                    wrapper_code = 0
                else:
                    state["status"] = "failed"
                    wrapper_code = int(code)
                write_state(path, state)
                return wrapper_code
            if time.monotonic() - last_heartbeat >= float(args.heartbeat_interval):
                touch_heartbeat(path)
                state["last_heartbeat_at"] = utc_now()
                sync_progress(path, state)
                write_state(path, state)
                last_heartbeat = time.monotonic()
            time.sleep(0.4)
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)


def stop_one(path: Path, grace_seconds: float) -> dict[str, Any]:
    state = load_state(path)
    if not state:
        return {"state_file": str(path), "status": "missing"}
    state = refresh_state(path, state) or {"run_id": path.stem, "status": "missing"}
    status = str(state.get("status") or "")
    pid = int(state.get("pid") or 0)
    pgid = int(state.get("pgid") or pid)
    if status in {"exited", "failed", "stopped"} or not process_alive(pid):
        return {"run_id": state.get("run_id") or path.stem, "status": state.get("status"), "pid": pid, "pgid": pgid}
    result = terminate_group(pgid, grace_seconds)
    latest = load_state(path)
    graceful_stop_codes = {-signal.SIGINT, -signal.SIGTERM, 130, 143}
    if (
        isinstance(latest, dict)
        and latest.get("status") == "stopped"
        and latest.get("exit_code") in graceful_stop_codes
    ):
        state = latest
        state["stop_result"] = "terminated"
        if result not in {"terminated", "not_found"}:
            state["descendant_stop_result"] = result
    else:
        state["status"] = "stopped"
        state["exit_code"] = -signal.SIGKILL if result == "killed" else -signal.SIGTERM
        state["stop_result"] = result
    state["stopped_at"] = utc_now()
    write_state(path, state)
    response = {
        "run_id": state.get("run_id") or path.stem,
        "status": "stopped",
        "pid": pid,
        "pgid": pgid,
        "exit_code": state.get("exit_code"),
        "stop_result": state.get("stop_result"),
    }
    if state.get("descendant_stop_result"):
        response["descendant_stop_result"] = state["descendant_stop_result"]
    return response


def stop_command(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir).expanduser()
    paths: list[Path]
    if args.all:
        paths = sorted(runs_dir.glob("*.json"))
    else:
        paths = [state_path(args.id, runs_dir)]
    results = [stop_one(path, args.grace) for path in paths]
    print(json.dumps(results if args.all else results[0], ensure_ascii=False, indent=2))
    return 0


def list_command(args: argparse.Namespace) -> int:
    runs_dir = Path(args.runs_dir).expanduser()
    rows: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*.json")):
        state = refresh_state(path) or {"run_id": path.stem, "status": "missing"}
        if args.active and str(state.get("status") or "") != RUNNING_STATUS:
            continue
        rows.append(state)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def status_command(args: argparse.Namespace) -> int:
    path = state_path(args.id, Path(args.runs_dir).expanduser())
    state = refresh_state(path)
    if not state:
        print(json.dumps({"run_id": args.id, "status": "missing", "state_file": str(path)}, indent=2))
        return 1
    print(json.dumps(state, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run and stop long ActionBook workflows.")
    parser.add_argument("--runs-dir", default=str(RUNS_DIR), help="Directory for run state files")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run a command in a tracked process group")
    run.add_argument("--id", required=True, help="Stable run id")
    run.add_argument("--cwd", default="", help="Working directory for the command")
    run.add_argument(
        "--progress-file",
        default="",
        help="Adapter contract/progress.json to mirror into the run state",
    )
    run.add_argument(
        "--heartbeat-interval",
        type=float,
        default=DEFAULT_HEARTBEAT_INTERVAL,
        help="Seconds between wrapper heartbeat and progress refreshes",
    )
    run.add_argument(
        "--heartbeat-stale-seconds",
        type=float,
        default=DEFAULT_HEARTBEAT_STALE_SECONDS,
        help="Mark a live wrapper stale after this heartbeat age",
    )
    run.add_argument("--replace", action="store_true", help="Stop an existing active run with the same id first")
    run.add_argument("--grace", type=float, default=5.0, help="Seconds to wait after SIGTERM before SIGKILL")
    run.add_argument("command", nargs=argparse.REMAINDER, help="Command after --")
    run.set_defaults(func=run_command_cli)

    stop = sub.add_parser("stop", help="Stop one tracked run or all active runs")
    stop_group = stop.add_mutually_exclusive_group(required=True)
    stop_group.add_argument("--id", help="Run id to stop")
    stop_group.add_argument("--all", action="store_true", help="Stop all tracked runs")
    stop.add_argument("--grace", type=float, default=5.0, help="Seconds to wait after SIGTERM before SIGKILL")
    stop.set_defaults(func=stop_command)

    status = sub.add_parser("status", help="Show one run state")
    status.add_argument("--id", required=True, help="Run id")
    status.set_defaults(func=status_command)

    list_runs = sub.add_parser("list", help="List tracked runs")
    list_runs.add_argument("--active", action="store_true", help="Only show active runs")
    list_runs.set_defaults(func=list_command)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
