from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import fcntl

from scripts.scheduler_lib.contracts import DEFAULT_LIMITS, SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sanitize_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value or "")).strip("._-")
    if not safe:
        raise ValueError("identifier is empty after sanitization")
    return safe


def task_id_prefix(site: str, intent: str, payload: dict[str, Any]) -> str:
    return sanitize_id(f"{site}_{intent}_{payload.get('query') or payload.get('url') or 'task'}")


class SchedulerStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.tasks_dir = self.root / "tasks"
        self.progress_dir = self.root / "progress"
        self.lock_path = self.root / "state.lock"
        self.events_path = self.root / "events.jsonl"
        self.snapshot_path = self.root / "state.json"

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def load_snapshot(self) -> dict[str, Any]:
        try:
            snapshot = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "schema_version": SCHEMA_VERSION,
                "limits": dict(DEFAULT_LIMITS),
                "tasks": {},
                "leases": {},
                "updated_at": utc_now(),
            }
        if not isinstance(snapshot, dict):
            raise ValueError(f"invalid scheduler snapshot: {self.snapshot_path}")
        return snapshot

    def _sync_directory(self, path: Path) -> None:
        dir_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _write_json(self, path: Path, payload: dict[str, Any], *, updated_at: str | None = None) -> dict[str, Any]:
        data = dict(payload)
        data["schema_version"] = SCHEMA_VERSION
        data["updated_at"] = updated_at or utc_now()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
        self._sync_directory(path.parent)
        return data

    def _append_event(self, payload: dict[str, Any]) -> None:
        event = dict(payload)
        event["schema_version"] = SCHEMA_VERSION
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._sync_directory(self.events_path.parent)

    def _new_task_id(self, site: str, intent: str, payload: dict[str, Any]) -> str:
        prefix = task_id_prefix(site, intent, payload)
        while True:
            task_id = f"{prefix}_{uuid4().hex[:10]}"
            if not (self.tasks_dir / f"{task_id}.json").exists():
                return task_id

    def create_task(self, *, site: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.locked():
            task_id = self._new_task_id(site, intent, payload)
            task_updated_at = utc_now()
            task = {
                "schema_version": SCHEMA_VERSION,
                "task_id": task_id,
                "site": site,
                "intent": intent,
                "payload": dict(payload),
                "status": "queued",
                "stage": "triaging",
                "attempts": 0,
                "followups": [],
                "updated_at": task_updated_at,
            }
            snapshot = self.load_snapshot()
            snapshot["tasks"][task_id] = {"status": task["status"], "stage": task["stage"]}
            self._append_event(
                {
                    "event_type": "task_created",
                    "task_id": task_id,
                    "site": site,
                    "intent": intent,
                    "status": task["status"],
                    "stage": task["stage"],
                    "at": utc_now(),
                }
            )
            task = self._write_json(self.tasks_dir / f"{task_id}.json", task, updated_at=task_updated_at)
            self._write_json(self.snapshot_path, snapshot)
        return task
