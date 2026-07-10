from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.scheduler_lib.state import SchedulerStore

def task_path(root: Path, task_id: str) -> Path:
    return SchedulerStore(root).task_path(task_id)


def load_task_record(root: Path, task_id: str) -> dict[str, Any]:
    return SchedulerStore(root).load_task_record(task_id)


def has_task_record(root: Path, task_id: str) -> bool:
    return SchedulerStore(root).has_task_record(task_id)


def task_run_id(task: dict[str, object]) -> str:
    return str(task.get("run_id") or task["task_id"])
