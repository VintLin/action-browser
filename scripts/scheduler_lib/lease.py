from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_lease(*, lease_id: str, session_id: str, tab_id: str, task_id: str) -> dict[str, str | int]:
    now = utc_now()
    return {
        "schema_version": 1,
        "lease_id": lease_id,
        "session_id": session_id,
        "tab_id": tab_id,
        "task_id": task_id,
        "opened_at": now,
        "last_active_at": now,
        "updated_at": now,
    }
