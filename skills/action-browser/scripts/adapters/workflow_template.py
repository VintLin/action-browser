#!/usr/bin/env python3
"""Copy this file to <site>_workflow.py and replace the example-specific parts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    ROOT_DIR = Path(__file__).resolve().parents[2]
    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))

from scripts.actionbook_interrupts import install_interrupt_handlers
from scripts.actionbook_session import ActionBookSession
from scripts.workflow_runtime import add_workflow_args, attach_workflow, evaluate, wait_until_stable, write_json


HOME_URL = "https://example.com"


def run_view(args: argparse.Namespace) -> int:
    book = attach_workflow(args, HOME_URL, ActionBookSession)
    wait_until_stable(book)
    result = evaluate(
        book,
        "(() => ({title: document.title, url: location.href}))()",
        "read example page",
    )
    output = Path(args.output)
    write_json(output, result)
    print(output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Example read-only workflow")
    add_workflow_args(parser)
    parser.add_argument("--output", required=True)
    parser.set_defaults(func=run_view)
    return parser


def main(argv: list[str] | None = None) -> int:
    install_interrupt_handlers()
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
