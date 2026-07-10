from __future__ import annotations

from typing import Any

SCHEMA_VERSION = 1

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_WAITING_USER = "waiting_user"
STATUS_BLOCKED = "blocked"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"

STAGE_TRIAGING = "triaging"
STAGE_USING_BROWSER = "using_browser"
STAGE_WAITING_USER_ACTION = "waiting_user_action"
STAGE_RETRYING = "retrying"

RESULT_QUALITY_FULL = "full"
RESULT_QUALITY_PARTIAL = "partial"

TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELED}
RUNNING_STATUSES = {STATUS_QUEUED, STATUS_RUNNING, STATUS_WAITING_USER}

DEFAULT_LIMITS = {
    "max_running_tasks": 2,
    "max_tabs_per_session": 5,
    "max_running_tasks_per_site": 1,
}


def build_scheduler_snapshot(*, updated_at: str, limits: dict[str, int] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "limits": dict(limits or DEFAULT_LIMITS),
        "tasks": {},
        "leases": {},
        "updated_at": updated_at,
    }


def build_task_record(
    *,
    task_id: str,
    site: str,
    intent: str,
    payload: dict[str, Any],
    updated_at: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "site": site,
        "intent": intent,
        "payload": dict(payload),
        "status": STATUS_QUEUED,
        "stage": STAGE_TRIAGING,
        "attempts": 0,
        "followups": [],
        "updated_at": updated_at,
    }


def build_task_snapshot(task: dict[str, Any]) -> dict[str, str]:
    return {"status": str(task["status"]), "stage": str(task["stage"])}


def build_task_created_event(*, task: dict[str, Any], at: str) -> dict[str, Any]:
    return {
        "event_type": "task_created",
        "task_id": task["task_id"],
        "site": task["site"],
        "intent": task["intent"],
        "status": task["status"],
        "stage": task["stage"],
        "at": at,
    }


def build_lease_record(*, lease_id: str, session_id: str, tab_id: str, task_id: str, now: str) -> dict[str, str | int]:
    return {
        "schema_version": SCHEMA_VERSION,
        "lease_id": lease_id,
        "session_id": session_id,
        "tab_id": tab_id,
        "task_id": task_id,
        "opened_at": now,
        "last_active_at": now,
        "updated_at": now,
    }


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
            status=STATUS_WAITING_USER,
            stage=STAGE_WAITING_USER_ACTION,
            reason_code=summary.get("reason_code"),
        )

    if not summary.get("ok"):
        failure = summary.get("failure")
        if isinstance(failure, dict) and failure.get("retryable"):
            return set_task_status(task, status=STATUS_RUNNING, stage=STAGE_RETRYING, reason_code=summary.get("reason_code"))
        return set_task_status(
            task,
            status=STATUS_BLOCKED if summary.get("status") == STATUS_BLOCKED else STATUS_FAILED,
            reason_code=summary.get("reason_code"),
        )

    requested = summary.get("requested_count", 0)
    collected = summary.get("collected_count", 0)
    return set_task_status(
        task,
        status=STATUS_COMPLETED,
        reason_code=summary.get("reason_code"),
        result_quality=RESULT_QUALITY_FULL if requested == 0 or collected >= requested else RESULT_QUALITY_PARTIAL,
    )
