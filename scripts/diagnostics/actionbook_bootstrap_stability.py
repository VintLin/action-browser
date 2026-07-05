#!/usr/bin/env python3
"""
Run repeated ActionBook extension-mode bootstrap rounds and save durable evidence.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
SESSION_HELPER = ROOT_DIR / "scripts/actionbook_session.py"


def normalize_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_command(args: list[str], timeout: float = 30.0, check: bool = False) -> dict[str, Any]:
    started = time.time()
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        stdout = normalize_output(result.stdout)
        stderr = normalize_output(result.stderr)
        returncode = result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = normalize_output(exc.stdout)
        stderr = normalize_output(exc.stderr)
        returncode = 124
    combined = (stdout + stderr).strip()
    payload = parse_mixed_output(combined)
    item = {
        "args": args,
        "returncode": returncode,
        "duration_ms": int((time.time() - started) * 1000),
        "stdout": stdout,
        "stderr": stderr,
        "payload": payload,
    }
    if check and returncode != 0:
        raise RuntimeError(combined or f"command failed: {' '.join(args)}")
    return item


def parse_mixed_output(text: str) -> Any:
    if not text:
        return None
    candidates = [text]
    lines = text.splitlines()
    if lines:
        candidates.append(lines[-1].strip())
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return text


def event(round_report: dict[str, Any], step: str, result: dict[str, Any] | None = None, note: str = "") -> None:
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "step": step,
    }
    if note:
        entry["note"] = note
    if result is not None:
        entry["returncode"] = result["returncode"]
        entry["duration_ms"] = result["duration_ms"]
    round_report.setdefault("timeline", []).append(entry)


def parse_json_from_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("payload")
    if isinstance(payload, dict):
        return payload
    raise RuntimeError(str(payload or "missing JSON output"))


def wait_for_chrome_stopped(timeout_secs: float = 12.0) -> bool:
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        probe = run_command(
            ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "Google Chrome"'],
            timeout=5.0,
        )
        if str(probe.get("stdout", "")).strip().lower() == "false":
            return True
        time.sleep(0.5)
    return False


def close_existing_chrome(round_report: dict[str, Any]) -> None:
    probe = run_command(
        ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "Google Chrome"'],
        timeout=5.0,
    )
    round_report["chrome_before"] = probe
    event(round_report, "chrome_process_probe", probe)
    if str(probe.get("stdout", "")).strip().lower() != "true":
        return
    quit_result = run_command(["osascript", "-e", 'tell application "Google Chrome" to quit'], timeout=10.0)
    round_report["chrome_quit"] = quit_result
    event(round_report, "chrome_quit", quit_result)
    stopped = wait_for_chrome_stopped()
    round_report["chrome_stopped"] = stopped
    event(round_report, "chrome_wait_stopped", note=f"stopped={stopped}")


def precheck() -> dict[str, Any]:
    return {
        "actionbook_version": run_command(["actionbook", "--version"], timeout=10.0),
        "extension_status": run_command(["actionbook", "extension", "status", "--json"], timeout=10.0),
        "extension_ping": run_command(["actionbook", "extension", "ping", "--json"], timeout=10.0),
        "list_sessions": run_command(["actionbook", "browser", "list-sessions", "--json"], timeout=10.0),
    }


def matching_session_ids(payload: dict[str, Any], session_prefix: str) -> list[str]:
    sessions = ((payload.get("data") or {}).get("sessions") or []) if isinstance(payload, dict) else []
    ids: list[str] = []
    for item in sessions:
        session_id = str((item or {}).get("session_id") or "").strip()
        if not session_id:
            continue
        if session_prefix and not session_id.startswith(session_prefix):
            continue
        ids.append(session_id)
    return ids


def close_known_sessions(round_report: dict[str, Any], session_prefix: str) -> None:
    sessions_result = run_command(["actionbook", "browser", "list-sessions", "--json"], timeout=10.0)
    round_report["list_sessions_before_cleanup"] = sessions_result
    event(round_report, "list_sessions_before_cleanup", sessions_result)
    payload = parse_json_from_result(sessions_result)
    matching_ids = matching_session_ids(payload, session_prefix)
    round_report["cleanup_session_prefix"] = session_prefix
    round_report["cleanup_candidate_session_ids"] = matching_ids
    round_report["cleanup_close_results"] = []
    for session_id in matching_ids:
        close_result = run_command(
            ["actionbook", "browser", "close", "--session", session_id, "--json"],
            timeout=15.0,
        )
        round_report["cleanup_close_results"].append(close_result)
        event(round_report, f"close_session:{session_id}", close_result)
        if close_result["returncode"] != 0:
            restart_daemon(round_report)


def run_diagnose(round_report: dict[str, Any], run_dir: Path, round_id: str) -> None:
    output_path = run_dir / f"{round_id}-diagnose.json"
    result = run_command(
        [
            "python3",
            str(ROOT_DIR / "scripts/diagnostics/actionbook_diagnose.py"),
            "--session-prefix",
            f"{round_id}-diag",
            "--url",
            "https://example.com",
            "--delays",
            "0,1,3",
            "--output",
            str(output_path),
        ],
        timeout=60.0,
    )
    round_report.setdefault("diagnostics", []).append(result)
    event(round_report, "diagnose", result, note=str(output_path))


def restart_daemon(round_report: dict[str, Any]) -> None:
    result = run_command(["pkill", "-f", "actionbook __daemon"], timeout=10.0)
    round_report.setdefault("repairs", []).append({"kind": "restart_daemon", "result": result})
    event(round_report, "restart_daemon", result)
    time.sleep(1.0)


def ensure_session(round_report: dict[str, Any], session_id: str) -> dict[str, Any]:
    result = run_command(
        [
            "python3",
            str(SESSION_HELPER),
            "ensure",
            "--session",
            session_id,
            "--url",
            "https://example.com",
            "--json",
        ],
        timeout=45.0,
    )
    round_report.setdefault("bootstrap_attempts", []).append(result)
    event(round_report, "ensure", result)
    return result


def list_tabs(round_report: dict[str, Any], session_id: str) -> dict[str, Any]:
    result = run_command(
        ["python3", str(SESSION_HELPER), "list-tabs", "--session", session_id, "--json"],
        timeout=20.0,
    )
    round_report.setdefault("list_tabs_checks", []).append(result)
    event(round_report, "list_tabs", result)
    return result


def reconnect_session(round_report: dict[str, Any], session_id: str, tab_id: str) -> dict[str, Any]:
    result = run_command(
        ["python3", str(SESSION_HELPER), "select-tab", "--session", session_id, "--tab", tab_id, "--json"],
        timeout=20.0,
    )
    round_report.setdefault("reconnect_checks", []).append(result)
    event(round_report, "reconnect_same_session", result)
    return result


def verify_tab(round_report: dict[str, Any], session_id: str, tab_id: str, label: str) -> None:
    commands = {
        "url": ["actionbook", "browser", "url", "--session", session_id, "--tab", tab_id, "--json"],
        "title": ["actionbook", "browser", "title", "--session", session_id, "--tab", tab_id, "--json"],
        "snapshot": ["actionbook", "browser", "snapshot", "--session", session_id, "--tab", tab_id, "--json"],
    }
    tab_report: dict[str, Any] = {}
    for key, command in commands.items():
        result = run_command(command, timeout=30.0)
        tab_report[key] = result
        event(round_report, f"{label}_{key}", result)
    round_report.setdefault("tab_checks", {})[label] = tab_report


def create_tab(round_report: dict[str, Any], session_id: str, url: str, label: str) -> str:
    result = run_command(
        ["python3", str(SESSION_HELPER), "new-tab", "--session", session_id, "--url", url, "--json"],
        timeout=45.0,
    )
    round_report.setdefault("new_tabs", []).append(result)
    event(round_report, f"new_tab:{label}", result)
    payload = parse_json_from_result(result)
    tab_id = str(payload.get("tab_id") or "").strip()
    if not tab_id:
        raise RuntimeError(f"missing tab id for {label}")
    return tab_id


def close_tab(round_report: dict[str, Any], session_id: str, tab_id: str, label: str) -> None:
    result = run_command(
        ["python3", str(SESSION_HELPER), "close-tab", "--session", session_id, "--tab", tab_id, "--json"],
        timeout=20.0,
    )
    round_report.setdefault("closed_tabs", []).append({"label": label, "result": result})
    event(round_report, f"close_tab:{label}", result)


def close_session(round_report: dict[str, Any], session_id: str) -> None:
    result = run_command(
        ["actionbook", "browser", "close", "--session", session_id, "--json"],
        timeout=20.0,
    )
    round_report["close_session"] = result
    event(round_report, "close_session", result)
    if result["returncode"] != 0:
        restart_daemon(round_report)


def load_verified_tabs(
    round_report: dict[str, Any],
    run_dir: Path,
    round_id: str,
    session_id: str,
) -> tuple[str, list[dict[str, Any]]]:
    tabs_payload = parse_json_from_result(list_tabs(round_report, session_id))
    tabs = tabs_payload.get("tabs") or []
    if tabs:
        first_tab = str((tabs[0] or {}).get("tab_id") or "").strip()
        return first_tab, tabs
    run_diagnose(round_report, run_dir, round_id)
    restart_daemon(round_report)
    retry_result = ensure_session(round_report, session_id)
    if retry_result["returncode"] != 0:
        raise RuntimeError(str(retry_result.get("payload") or retry_result.get("stderr") or "ensure failed after empty tabs"))
    retry_payload = parse_json_from_result(retry_result)
    retry_tab = str(retry_payload.get("tab_id") or "").strip()
    reconnect_session(round_report, session_id, retry_tab)
    tabs_payload = parse_json_from_result(list_tabs(round_report, session_id))
    tabs = tabs_payload.get("tabs") or []
    if not tabs:
        raise RuntimeError("list-tabs returned no tabs after ensure retry")
    return retry_tab, tabs


def exercise_round(run_dir: Path, index: int, quit_chrome: bool, session_prefix: str) -> dict[str, Any]:
    round_id = f"round-{index:02d}"
    session_id = f"{session_prefix}{index:02d}"
    report: dict[str, Any] = {
        "round_id": round_id,
        "session_id": session_id,
        "session_prefix": session_prefix,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "status": "running",
        "timeline": [],
        "repairs": [],
    }
    try:
        report["precheck"] = precheck()
        event(report, "precheck_complete")
        if quit_chrome:
            close_existing_chrome(report)
        close_known_sessions(report, session_prefix=session_prefix)

        base_result = ensure_session(report, session_id)
        if base_result["returncode"] != 0:
            run_diagnose(report, run_dir, round_id)
            restart_daemon(report)
            base_result = ensure_session(report, session_id)
            if base_result["returncode"] != 0:
                raise RuntimeError(str(base_result.get("payload") or base_result.get("stderr") or "ensure failed"))

        base_payload = parse_json_from_result(base_result)
        base_tab = str(base_payload.get("tab_id") or "").strip()
        if not base_tab:
            raise RuntimeError("ensure returned no tab id")

        reconnect_session(report, session_id, base_tab)
        first_tab, tabs = load_verified_tabs(report, run_dir, round_id, session_id)
        if first_tab:
            base_tab = first_tab

        verify_tab(report, session_id, base_tab, "base")

        tab_specs = [
            ("tab2", "https://example.org"),
            ("tab3", "https://example.net"),
        ]
        created: list[tuple[str, str]] = [("base", base_tab)]
        for label, url in tab_specs:
            tab_id = create_tab(report, session_id, url, label)
            created.append((label, tab_id))
            verify_tab(report, session_id, tab_id, label)

        for label, tab_id in reversed(created[1:]):
            close_tab(report, session_id, tab_id, label)
        close_tab(report, session_id, base_tab, "base")
        close_session(report, session_id)
        if quit_chrome:
            close_existing_chrome(report)

        report["status"] = "success"
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        return report
    except Exception as exc:  # noqa: BLE001
        report["status"] = "failed"
        report["error"] = str(exc)
        report["finished_at"] = datetime.now().isoformat(timespec="seconds")
        return report


def summarize(reports: list[dict[str, Any]]) -> dict[str, Any]:
    failure_counts: dict[str, int] = {}
    for report in reports:
        if report.get("status") != "failed":
            continue
        message = str(report.get("error") or "unknown failure")
        failure_counts[message] = failure_counts.get(message, 0) + 1
    return {
        "runs": len(reports),
        "successes": sum(1 for report in reports if report.get("status") == "success"),
        "failures": sum(1 for report in reports if report.get("status") == "failed"),
        "failure_counts": failure_counts,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repeated ActionBook extension bootstrap stability rounds.")
    parser.add_argument("--rounds", type=int, default=5, help="How many successful rounds to target")
    parser.add_argument("--max-attempts", type=int, default=8, help="Hard cap on total rounds")
    parser.add_argument("--output-dir", default="", help="Directory for durable reports")
    parser.add_argument("--quit-chrome", action="store_true", help="Force-quit Chrome before and after each round")
    parser.add_argument(
        "--session-prefix",
        default="bootstrap-stability-",
        help="Only create/clean up ActionBook sessions with this prefix",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.output_dir) if args.output_dir else ROOT_DIR / "diagnostics/actionbook/bootstrap-stability" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict[str, Any]] = []
    successes = 0
    attempts = 0
    while successes < args.rounds and attempts < args.max_attempts:
        attempts += 1
        report = exercise_round(run_dir, attempts, quit_chrome=args.quit_chrome, session_prefix=args.session_prefix)
        reports.append(report)
        (run_dir / f"{report['round_id']}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if report.get("status") == "success":
            successes += 1

    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target_successes": args.rounds,
        "max_attempts": args.max_attempts,
        "reports": [report["round_id"] for report in reports],
        "summary": summarize(reports),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(run_dir), **summary["summary"]}, ensure_ascii=False, indent=2))
    return 0 if successes >= args.rounds else 1


if __name__ == "__main__":
    raise SystemExit(main())
