#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run a helper-first ActionBook end-to-end smoke and write a report.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_json_maybe(text: str) -> Any:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.rfind("\n{")
    if start != -1:
        return json.loads(raw[start + 1 :])
    start = raw.find("{")
    if start != -1:
        return json.loads(raw[start:])
    return raw


def run_command(
    args: list[str],
    *,
    cwd: Path,
    timeout: float = 180.0,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(args, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    return {
        "cmd": args,
        "rc": result.returncode,
        "payload": parse_json_maybe(text),
        "text": text,
    }


def step(name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "result": result}


def metadata_summary(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"url": data.get("url"), "title": data.get("title")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run helper-first ActionBook E2E smoke")
    parser.add_argument("--output-dir", default="", help="Directory for the smoke report")
    parser.add_argument("--generic-url", default="https://example.com", help="Generic URL for initial unsupported flow")
    parser.add_argument("--serial-url-1", default="https://example.org", help="First same-tab serial URL")
    parser.add_argument(
        "--serial-url-2",
        default="https://www.iana.org/domains/reserved",
        help="Second same-tab serial URL",
    )
    parser.add_argument("--parallel-url", default="https://example.net", help="URL for the second parallel tab")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    output_dir = Path(args.output_dir).expanduser() if args.output_dir else root / "diagnostics" / "e2e" / (
        "smoke-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    scheduler_dir = Path(tempfile.mkdtemp(prefix="scheduler.", dir=str(output_dir)))
    session_id = f"e2e-smoke-{uuid.uuid4().hex[:8]}"
    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "output_dir": str(output_dir),
        "scheduler_dir": str(scheduler_dir),
        "steps": [],
    }

    scheduler_env = {"ACTION_BROWSER_SCHEDULER_DIR": str(scheduler_dir)}
    report["steps"].append(
        step(
            "scheduler_submit_taobao",
            run_command(
                ["python3", "scripts/scheduler.py", "submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书", "--limit", "3"],
                cwd=root,
                extra_env=scheduler_env,
            ),
        )
    )
    report["steps"].append(
        step(
            "scheduler_submit_douban",
            run_command(
                ["python3", "scripts/scheduler.py", "submit", "--site", "douban", "--intent", "search", "--query", "儿童童书", "--limit", "3"],
                cwd=root,
                extra_env=scheduler_env,
            ),
        )
    )
    report["steps"].append(
        step(
            "scheduler_submit_generic",
            run_command(
                ["python3", "scripts/scheduler.py", "submit", "--site", "generic", "--intent", "capture", "--query", args.generic_url, "--limit", "1"],
                cwd=root,
                extra_env=scheduler_env,
            ),
        )
    )
    report["steps"].append(
        step(
            "scheduler_list",
            run_command(["python3", "scripts/scheduler.py", "list"], cwd=root, extra_env=scheduler_env),
        )
    )

    ensure = run_command(
        ["python3", "scripts/actionbook_session.py", "ensure", "--session", session_id, "--url", args.generic_url, "--json"],
        cwd=root,
        timeout=120.0,
    )
    report["steps"].append(step("helper_ensure", ensure))
    if ensure["rc"] != 0:
        report_path = output_dir / "report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(report_path), "status": "ensure_failed"}, ensure_ascii=False, indent=2))
        return 1
    first_tab = str((ensure["payload"] or {}).get("tab_id") or "")
    report["first_tab"] = first_tab

    unsupported_dir = output_dir / "unsupported-current"
    report["steps"].append(
        step(
            "unsupported_generic_current",
            run_command(
                [
                    "python3",
                    "scripts/webpage_markdown.py",
                    "current",
                    "--session",
                    session_id,
                    "--tab",
                    first_tab,
                    "--output-dir",
                    str(unsupported_dir),
                    "--allow-short",
                ],
                cwd=root,
            ),
        )
    )

    report["steps"].append(
        step(
            "serial_goto_1",
            run_command(
                ["actionbook", "browser", "goto", args.serial_url_1, "--session", session_id, "--tab", first_tab, "--json"],
                cwd=root,
                timeout=60.0,
            ),
        )
    )
    serial_1_dir = output_dir / "serial-step-1"
    report["steps"].append(
        step(
            "serial_capture_1",
            run_command(
                [
                    "python3",
                    "scripts/webpage_markdown.py",
                    "current",
                    "--session",
                    session_id,
                    "--tab",
                    first_tab,
                    "--output-dir",
                    str(serial_1_dir),
                    "--allow-short",
                ],
                cwd=root,
            ),
        )
    )

    report["steps"].append(
        step(
            "serial_goto_2",
            run_command(
                ["actionbook", "browser", "goto", args.serial_url_2, "--session", session_id, "--tab", first_tab, "--json"],
                cwd=root,
                timeout=60.0,
            ),
        )
    )
    serial_2_dir = output_dir / "serial-step-2"
    report["steps"].append(
        step(
            "serial_capture_2",
            run_command(
                [
                    "python3",
                    "scripts/webpage_markdown.py",
                    "current",
                    "--session",
                    session_id,
                    "--tab",
                    first_tab,
                    "--output-dir",
                    str(serial_2_dir),
                    "--allow-short",
                ],
                cwd=root,
            ),
        )
    )

    new_tab = run_command(
        ["python3", "scripts/actionbook_session.py", "new-tab", "--session", session_id, "--url", args.parallel_url, "--json"],
        cwd=root,
        timeout=120.0,
    )
    report["steps"].append(step("helper_new_tab", new_tab))
    second_tab = str((new_tab["payload"] or {}).get("tab_id") or "")
    report["parallel_tabs"] = [first_tab, second_tab]

    parallel_a_dir = output_dir / "parallel-a"
    parallel_b_dir = output_dir / "parallel-b"
    cmd_a = [
        "python3",
        "scripts/webpage_markdown.py",
        "current",
        "--session",
        session_id,
        "--tab",
        first_tab,
        "--output-dir",
        str(parallel_a_dir),
        "--allow-short",
    ]
    cmd_b = [
        "python3",
        "scripts/webpage_markdown.py",
        "current",
        "--session",
        session_id,
        "--tab",
        second_tab,
        "--output-dir",
        str(parallel_b_dir),
        "--allow-short",
    ]
    proc_a = subprocess.Popen(cmd_a, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proc_b = subprocess.Popen(cmd_b, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out_a, err_a = proc_a.communicate(timeout=180.0)
    out_b, err_b = proc_b.communicate(timeout=180.0)
    report["steps"].append(
        step(
            "parallel_capture_a",
            {"cmd": cmd_a, "rc": proc_a.returncode, "payload": parse_json_maybe(((out_a or "") + (err_a or "")).strip())},
        )
    )
    report["steps"].append(
        step(
            "parallel_capture_b",
            {"cmd": cmd_b, "rc": proc_b.returncode, "payload": parse_json_maybe(((out_b or "") + (err_b or "")).strip())},
        )
    )

    report["steps"].append(
        step(
            "helper_close_session",
            run_command(["actionbook", "browser", "close", "--session", session_id, "--json"], cwd=root, timeout=60.0),
        )
    )

    report["artifacts"] = {
        "unsupported": metadata_summary(unsupported_dir / "metadata.json") if (unsupported_dir / "metadata.json").exists() else {},
        "serial_1": metadata_summary(serial_1_dir / "metadata.json") if (serial_1_dir / "metadata.json").exists() else {},
        "serial_2": metadata_summary(serial_2_dir / "metadata.json") if (serial_2_dir / "metadata.json").exists() else {},
        "parallel_a": metadata_summary(parallel_a_dir / "metadata.json") if (parallel_a_dir / "metadata.json").exists() else {},
        "parallel_b": metadata_summary(parallel_b_dir / "metadata.json") if (parallel_b_dir / "metadata.json").exists() else {},
    }

    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(report_path), "session_id": session_id, "parallel_tabs": report["parallel_tabs"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
