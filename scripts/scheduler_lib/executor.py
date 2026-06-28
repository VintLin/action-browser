from __future__ import annotations

from pathlib import Path

from scripts import actionbook_run


def call_actionbook_run(argv: list[str]) -> int:
    return actionbook_run.main(argv)


def progress_path(root: Path, task_id: str) -> Path:
    return root / "progress" / f"{task_id}.json"
