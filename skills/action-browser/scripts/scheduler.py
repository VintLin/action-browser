from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts import actionbook_run
from scripts.actionbook_session import ActionBookSession
from scripts.scheduler_lib.contracts import TERMINAL_STATUSES
from scripts.scheduler_lib.executor import has_active_run, load_run_state
from scripts.scheduler_lib.lifecycle import has_task_record, load_task_record, task_run_id
from scripts.scheduler_lib.reconcile import (
    reconcile_task_state,
    resolve_output_dir,
    resolve_progress_path,
    resolve_summary_path,
)
from scripts.scheduler_lib.state import SchedulerStore


def scheduler_root() -> Path:
    return Path(
        os.environ.get("ACTION_BROWSER_SCHEDULER_DIR", Path.home() / ".action-browser" / "scheduler")
    ).expanduser()


def emit_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


def stop_missing_payload(task_id: str, run_id: str) -> dict[str, object]:
    return {"error": "run_not_found", "task_id": task_id, "run_id": run_id}


def task_tab_is_alive(task: dict[str, object], run_state: dict[str, object] | None) -> bool:
    if not isinstance(run_state, dict) or run_state.get("status") != "running":
        return False
    session_id = str(task.get("session_id") or "").strip()
    tab_id = str(task.get("tab_id") or "").strip()
    if not session_id or not tab_id:
        # ponytail: current task records do not always persist leased tab ids yet.
        return True
    try:
        session = ActionBookSession(session_id, tab_id, allow_adopt=False)
        session.use_tab(tab_id)
    except Exception:
        return False
    return True


def cmd_submit(args: argparse.Namespace) -> int:
    if args.limit <= 0:
        emit_json({"error": "invalid_limit", "limit": args.limit})
        return 1
    store = SchedulerStore(scheduler_root())
    payload = {"query": args.query, "limit": args.limit}
    task = store.create_task(site=args.site, intent=args.intent, payload=payload)
    emit_json({"task_id": task["task_id"], "status": task["status"]})
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    snapshot = SchedulerStore(scheduler_root()).load_snapshot()
    emit_json(snapshot.get("tasks", {}))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = scheduler_root()
    if not has_task_record(root, args.task):
        emit_json({"error": "task_not_found", "task_id": args.task})
        return 1
    emit_json(load_task_record(root, args.task))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    root = scheduler_root()
    if not has_task_record(root, args.task):
        emit_json({"error": "task_not_found", "task_id": args.task})
        return 1
    task = load_task_record(root, args.task)
    run_id = task_run_id(task)
    if not has_active_run(run_id):
        emit_json(stop_missing_payload(args.task, run_id))
        return 1
    captured = StringIO()
    with redirect_stdout(captured):
        exit_code = actionbook_run.main(["stop", "--id", run_id])
    output = captured.getvalue()
    payload: dict[str, object] | None = None
    if output.strip():
        try:
            decoded = json.loads(output)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            payload = decoded
    if exit_code == 0 and payload and payload.get("status") == "missing":
        emit_json(stop_missing_payload(args.task, run_id))
        return 1
    if output:
        print(output, end="")
    return exit_code


def cmd_reconcile(_args: argparse.Namespace) -> int:
    root = scheduler_root()
    store = SchedulerStore(root)
    rows: list[dict[str, object]] = []
    for task in store.list_task_records():
        if str(task.get("status") or "") in TERMINAL_STATUSES:
            continue
        run_id = task_run_id(task)
        run_state = load_run_state(run_id)
        output_dir = resolve_output_dir(task)
        summary_path = resolve_summary_path(task)
        progress_path = resolve_progress_path(task, root)
        tab_alive = task_tab_is_alive(task, run_state)
        next_task = reconcile_task_state(
            dict(task),
            run_state=run_state,
            tab_alive=tab_alive,
            summary_path=summary_path,
            progress_path=progress_path,
            output_dir=output_dir,
        )
        persisted = store.save_task_record(next_task, event_type="task_reconciled")
        rows.append(
            {
                "task_id": persisted["task_id"],
                "status": persisted.get("status"),
                "stage": persisted.get("stage"),
                "reason_code": persisted.get("reason_code"),
                "result_quality": persisted.get("result_quality"),
            }
        )
    emit_json({"tasks": rows, "count": len(rows)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit")
    submit.add_argument("--site", required=True)
    submit.add_argument("--intent", required=True)
    submit.add_argument("--query", required=True)
    submit.add_argument("--limit", type=int, default=20)
    submit.set_defaults(func=cmd_submit)

    listing = subparsers.add_parser("list")
    listing.set_defaults(func=cmd_list)

    status = subparsers.add_parser("status")
    status.add_argument("--task", required=True)
    status.set_defaults(func=cmd_status)

    stop = subparsers.add_parser("stop")
    stop.add_argument("--task", required=True)
    stop.set_defaults(func=cmd_stop)

    reconcile = subparsers.add_parser("reconcile")
    reconcile.set_defaults(func=cmd_reconcile)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
