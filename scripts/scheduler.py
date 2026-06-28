from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[1]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.scheduler_lib.executor import call_actionbook_run
from scripts.scheduler_lib.lifecycle import has_task_record, load_task_record, task_run_id
from scripts.scheduler_lib.state import SchedulerStore


def scheduler_root() -> Path:
    return Path(
        os.environ.get("ACTION_BROWSER_SCHEDULER_DIR", Path.home() / ".action-browser" / "scheduler")
    ).expanduser()


def emit_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False))


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
    return call_actionbook_run(["stop", "--id", task_run_id(task)])


def cmd_reconcile(_args: argparse.Namespace) -> int:
    emit_json({"error": "not_implemented", "command": "reconcile"})
    return 1


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
