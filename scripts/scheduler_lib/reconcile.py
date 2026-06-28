from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def apply_summary_result(task: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    task["reason_code"] = summary.get("reason_code")
    task["completed_items"] = summary.get("collected_count", 0)
    task["requested_items"] = summary.get("requested_count", 0)

    if summary.get("needs_user_action"):
        task["status"] = "waiting_user"
        task["stage"] = "waiting_user_action"
        return task

    if not summary.get("ok"):
        task["status"] = "blocked" if summary.get("status") == "blocked" else "failed"
        return task

    task["status"] = "completed"
    requested = summary.get("requested_count", 0)
    collected = summary.get("collected_count", 0)
    task["result_quality"] = "full" if requested == 0 or collected >= requested else "partial"
    return task


def reconcile_task_state(
    task: dict[str, Any],
    *,
    run_state: dict[str, Any] | None,
    tab_alive: bool,
    summary_path: Path,
) -> dict[str, Any]:
    if run_state and run_state.get("status") == "running" and tab_alive:
        task["status"] = "running"
        task["stage"] = task.get("stage") or "using_browser"
        return task
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return apply_summary_result(task, summary)
    if run_state and run_state.get("status") == "running" and not tab_alive:
        task["status"] = "failed"
        task["reason_code"] = "tab_lost"
        return task
    task["status"] = "blocked"
    task["reason_code"] = "run_missing"
    return task
