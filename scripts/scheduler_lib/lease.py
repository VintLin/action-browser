from __future__ import annotations

from scripts.scheduler_lib.contracts import build_lease_record
from scripts.scheduler_lib.state import utc_now


def build_lease(*, lease_id: str, session_id: str, tab_id: str, task_id: str) -> dict[str, str | int]:
    now = utc_now()
    return build_lease_record(lease_id=lease_id, session_id=session_id, tab_id=tab_id, task_id=task_id, now=now)
