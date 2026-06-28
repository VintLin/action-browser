from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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
        task["status"] = "completed"
        if summary.get("collected_count", 0) < summary.get("requested_count", 0):
            task["result_quality"] = "partial"
        return task
    if run_state and run_state.get("status") == "running" and not tab_alive:
        task["status"] = "failed"
        task["reason_code"] = "tab_lost"
        return task
    task["status"] = "blocked"
    task["reason_code"] = "run_missing"
    return task
