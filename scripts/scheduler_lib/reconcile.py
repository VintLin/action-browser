from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def set_task_status(
    task: dict[str, Any],
    *,
    status: str,
    stage: str | None = None,
    reason_code: str | None = None,
    result_quality: str | None = None,
) -> dict[str, Any]:
    task["status"] = status
    task["stage"] = stage
    task["reason_code"] = reason_code
    task["result_quality"] = result_quality
    return task


def apply_summary_result(task: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    task["completed_items"] = summary.get("collected_count", 0)
    task["requested_items"] = summary.get("requested_count", 0)

    if summary.get("needs_user_action"):
        return set_task_status(
            task,
            status="waiting_user",
            stage="waiting_user_action",
            reason_code=summary.get("reason_code"),
        )

    if not summary.get("ok"):
        return set_task_status(
            task,
            status="blocked" if summary.get("status") == "blocked" else "failed",
            reason_code=summary.get("reason_code"),
        )

    requested = summary.get("requested_count", 0)
    collected = summary.get("collected_count", 0)
    return set_task_status(
        task,
        status="completed",
        reason_code=summary.get("reason_code"),
        result_quality="full" if requested == 0 or collected >= requested else "partial",
    )


def reconcile_task_state(
    task: dict[str, Any],
    *,
    run_state: dict[str, Any] | None,
    tab_alive: bool,
    summary_path: Path,
) -> dict[str, Any]:
    if run_state and run_state.get("status") == "running" and tab_alive:
        return set_task_status(task, status="running", stage=task.get("stage") or "using_browser")
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return apply_summary_result(task, summary)
    if run_state and run_state.get("status") == "running" and not tab_alive:
        return set_task_status(task, status="failed", reason_code="tab_lost")
    return set_task_status(task, status="blocked", reason_code="run_missing")
