from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.scheduler_lib.contracts import (
    STATUS_BLOCKED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STAGE_USING_BROWSER,
    apply_summary_result,
    set_task_status,
)


def reconcile_task_state(
    task: dict[str, Any],
    *,
    run_state: dict[str, Any] | None,
    tab_alive: bool,
    summary_path: Path,
) -> dict[str, Any]:
    if run_state and run_state.get("status") == STATUS_RUNNING and tab_alive:
        return set_task_status(task, status=STATUS_RUNNING, stage=task.get("stage") or STAGE_USING_BROWSER)
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        return apply_summary_result(task, summary)
    if run_state and run_state.get("status") == STATUS_RUNNING and not tab_alive:
        return set_task_status(task, status=STATUS_FAILED, reason_code="tab_lost")
    return set_task_status(task, status=STATUS_BLOCKED, reason_code="run_missing")
