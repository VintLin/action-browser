from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def task_path(root: Path, task_id: str) -> Path:
    return Path(root) / "tasks" / f"{task_id}.json"


def load_task_record(root: Path, task_id: str) -> dict[str, Any]:
    return json.loads(task_path(root, task_id).read_text(encoding="utf-8"))


def has_task_record(root: Path, task_id: str) -> bool:
    return task_path(root, task_id).exists()
