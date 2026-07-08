#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run a small ActionBook extension-session persistence experiment and write a
durable report.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def parse_delay_list(raw: str) -> list[float]:
    values: list[float] = []
    for part in str(raw or "").split(","):
        item = part.strip()
        if not item:
            continue
        values.append(float(item))
    if not values:
        raise ValueError("at least one delay is required")
    return sorted(set(values))


def parse_json_output(output: str) -> Any:
    text = str(output or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def run_probe_command(args: list[str], *, shell: bool = False, timeout: float = 30.0) -> dict[str, Any]:
    started = time.time()
    if shell:
        command_text = " ".join(shlex.quote(part) for part in args)
        result = subprocess.run(
            ["/bin/zsh", "-lc", command_text],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    else:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    output = (stdout + stderr).strip()
    payload = parse_json_output(output)
    error_code = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            error_code = str(error.get("code") or "").strip()
    return {
        "args": args,
        "shell": shell,
        "returncode": result.returncode,
        "duration_ms": int((time.time() - started) * 1000),
        "stdout": stdout,
        "stderr": stderr,
        "payload": payload,
        "error_code": error_code,
    }


def classify_result(result: dict[str, Any]) -> str:
    payload = result.get("payload")
    if isinstance(payload, dict) and payload.get("ok") is True:
        return "ok"
    if result.get("error_code") == "SESSION_NOT_FOUND":
        return "session_not_found"
    if result.get("error_code"):
        return str(result["error_code"]).lower()
    if result.get("returncode") == 0:
        return "ok_non_json"
    return "error"


def build_probe_result(name: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "kind": classify_result(result),
        "returncode": result["returncode"],
        "shell": result["shell"],
        "duration_ms": result["duration_ms"],
        "error_code": result["error_code"],
        "payload": result["payload"],
    }


def summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    probes = report.get("polls") or []
    extension_connected = False
    direct_status_visible = False
    shell_status_visible = False
    list_tabs_visible = False
    for poll in probes:
        ext = poll.get("extension") or {}
        ext_payload = ext.get("payload")
        if isinstance(ext_payload, dict):
            data = ext_payload.get("data")
            if isinstance(data, dict) and data.get("extension_connected") is True:
                extension_connected = True
        direct_status_visible = direct_status_visible or (poll.get("status_direct", {}).get("kind") == "ok")
        shell_status_visible = shell_status_visible or (poll.get("status_shell", {}).get("kind") == "ok")
        list_tabs_visible = list_tabs_visible or (poll.get("list_tabs_direct", {}).get("kind") == "ok")
    start = report.get("start") or {}
    close = report.get("close") or {}
    return {
        "start_ok": start.get("kind") == "ok",
        "extension_connected_after_start": extension_connected,
        "session_visible_direct": direct_status_visible,
        "session_visible_in_fresh_shell": shell_status_visible,
        "tabs_visible_direct": list_tabs_visible,
        "close_ok": close.get("kind") in {"ok", "session_not_found"},
    }


def summarize_batch(reports: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(reports)
    if total == 0:
        return {"runs": 0}
    return {
        "runs": total,
        "start_ok_runs": sum(1 for report in reports if report.get("summary", {}).get("start_ok")),
        "extension_connected_runs": sum(
            1 for report in reports if report.get("summary", {}).get("extension_connected_after_start")
        ),
        "session_visible_direct_runs": sum(
            1 for report in reports if report.get("summary", {}).get("session_visible_direct")
        ),
        "session_visible_in_fresh_shell_runs": sum(
            1 for report in reports if report.get("summary", {}).get("session_visible_in_fresh_shell")
        ),
        "tabs_visible_direct_runs": sum(
            1 for report in reports if report.get("summary", {}).get("tabs_visible_direct")
        ),
        "close_ok_runs": sum(1 for report in reports if report.get("summary", {}).get("close_ok")),
    }


def poll_session(session_id: str, delay_secs: float) -> dict[str, Any]:
    extension = run_probe_command(["actionbook", "extension", "status", "--json"], timeout=15.0)
    status_direct = run_probe_command(
        ["actionbook", "browser", "status", "--session", session_id, "--json"],
        timeout=15.0,
    )
    status_shell = run_probe_command(
        ["actionbook", "browser", "status", "--session", session_id, "--json"],
        shell=True,
        timeout=15.0,
    )
    list_tabs_direct = run_probe_command(
        ["actionbook", "browser", "list-tabs", "--session", session_id, "--json"],
        timeout=15.0,
    )
    return {
        "delay_secs": delay_secs,
        "extension": build_probe_result("extension_status", extension),
        "status_direct": build_probe_result("browser_status_direct", status_direct),
        "status_shell": build_probe_result("browser_status_shell", status_shell),
        "list_tabs_direct": build_probe_result("browser_list_tabs_direct", list_tabs_direct),
    }


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("diagnostics/actionbook") / f"{stamp}-session-persistence.json"


def default_batch_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("diagnostics/actionbook") / f"{stamp}-session-persistence-batch.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose ActionBook extension session persistence.")
    parser.add_argument("--session-prefix", default="diag", help="Prefix for the temporary ActionBook session id")
    parser.add_argument("--url", default="https://example.com", help="URL to open during the start step")
    parser.add_argument("--delays", default="0,1,3", help="Comma-separated poll delays in seconds")
    parser.add_argument("--output", default="", help="Write report JSON to this path")
    parser.add_argument("--runs", type=int, default=1, help="Repeat the diagnosis this many times")
    parser.add_argument("--keep-session", action="store_true", help="Skip closing the test session")
    return parser


def run_diagnosis(*, session_prefix: str, url: str, delays: list[float], keep_session: bool, output_path: Path) -> dict[str, Any]:
    session_id = f"{session_prefix}-{uuid.uuid4().hex[:8]}"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "session_id": session_id,
        "url": url,
        "delays": delays,
        "pre_start_extension": [],
        "start": {},
        "polls": [],
        "close": {},
        "summary": {},
    }

    for _ in range(3):
        report["pre_start_extension"].append(
            build_probe_result(
                "extension_status_pre_start",
                run_probe_command(["actionbook", "extension", "status", "--json"], timeout=15.0),
            )
        )
        time.sleep(1.0)

    report["start"] = build_probe_result(
        "browser_start",
        run_probe_command(
            [
                "actionbook",
                "browser",
                "start",
                "--mode",
                "extension",
                "--session",
                session_id,
                "--open-url",
                url,
                "--json",
            ],
            timeout=30.0,
        ),
    )

    started = time.time()
    for delay_secs in delays:
        wait_secs = delay_secs - (time.time() - started)
        if wait_secs > 0:
            time.sleep(wait_secs)
        report["polls"].append(poll_session(session_id, delay_secs))

    if not keep_session:
        report["close"] = build_probe_result(
            "browser_close",
            run_probe_command(
                ["actionbook", "browser", "close", "--session", session_id, "--json"],
                timeout=15.0,
            ),
        )

    report["summary"] = summarize_report(report)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["output"] = str(output_path)
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    delays = parse_delay_list(args.delays)
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    if args.runs == 1:
        output_path = Path(args.output) if args.output else default_output_path()
        report = run_diagnosis(
            session_prefix=args.session_prefix,
            url=args.url,
            delays=delays,
            keep_session=args.keep_session,
            output_path=output_path,
        )
        print(
            json.dumps(
                {"output": report["output"], "session_id": report["session_id"], "summary": report["summary"]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    reports: list[dict[str, Any]] = []
    for index in range(args.runs):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = Path("diagnostics/actionbook") / f"{stamp}-session-persistence-run{index + 1}.json"
        reports.append(
            run_diagnosis(
                session_prefix=args.session_prefix,
                url=args.url,
                delays=delays,
                keep_session=args.keep_session,
                output_path=output_path,
            )
        )
    batch_output = Path(args.output) if args.output else default_batch_output_path()
    batch_output.parent.mkdir(parents=True, exist_ok=True)
    batch_report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "runs": args.runs,
        "delays": delays,
        "reports": [
            {"output": report["output"], "session_id": report["session_id"], "summary": report["summary"]}
            for report in reports
        ],
        "summary": summarize_batch(reports),
    }
    batch_output.write_text(json.dumps(batch_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(batch_output), **batch_report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
