from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scripts.scheduler_lib.lifecycle import load_task_record
from scripts.scheduler_lib.state import SchedulerStore


def scheduler_root() -> Path:
    return Path(
        os.environ.get("ACTION_BROWSER_SCHEDULER_DIR", Path.home() / ".action-browser" / "scheduler")
    ).expanduser()


def cmd_submit(args: argparse.Namespace) -> int:
    store = SchedulerStore(scheduler_root())
    payload = {"query": args.query, "limit": args.limit}
    task = store.create_task(site=args.site, intent=args.intent, payload=payload)
    print(json.dumps({"task_id": task["task_id"], "status": task["status"]}, ensure_ascii=False, indent=2))
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    snapshot = SchedulerStore(scheduler_root()).load_snapshot()
    print(json.dumps(snapshot.get("tasks", {}), ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(load_task_record(scheduler_root(), args.task), ensure_ascii=False, indent=2))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    print(json.dumps({"task_id": args.task, "status": "stop_not_implemented"}, ensure_ascii=False, indent=2))
    return 0


def cmd_reconcile(_args: argparse.Namespace) -> int:
    print(json.dumps({"status": "reconcile_not_implemented"}, ensure_ascii=False, indent=2))
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
