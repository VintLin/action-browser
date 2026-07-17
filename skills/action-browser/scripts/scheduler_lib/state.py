from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import fcntl

from scripts.scheduler_lib.contracts import (
    DEFAULT_LIMITS,
    SCHEMA_VERSION,
    build_scheduler_snapshot,
    build_task_created_event,
    build_task_record,
    build_task_snapshot,
)


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
            return build_scheduler_snapshot(updated_at=utc_now(), limits=DEFAULT_LIMITS)
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != SCHEMA_VERSION:
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
            if not self.task_path(task_id).exists():
                return task_id

    def task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def has_task_record(self, task_id: str) -> bool:
        return self.task_path(task_id).exists()

    def load_task_record(self, task_id: str) -> dict[str, Any]:
        payload = json.loads(self.task_path(task_id).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"invalid scheduler task record: {self.task_path(task_id)}")
        return payload

    def list_task_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in sorted(self.tasks_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(f"invalid scheduler task record: {path}")
            records.append(payload)
        return records

    def save_task_record(self, task: dict[str, Any], *, event_type: str) -> dict[str, Any]:
        task_id = str(task["task_id"])
        with self.locked():
            updated_at = utc_now()
            persisted = self._write_json(self.task_path(task_id), task, updated_at=updated_at)
            snapshot = self.load_snapshot()
            snapshot["tasks"][task_id] = build_task_snapshot(persisted)
            self._append_event(
                {
                    "event_type": event_type,
                    "task_id": task_id,
                    "status": persisted.get("status"),
                    "stage": persisted.get("stage"),
                    "reason_code": persisted.get("reason_code"),
                    "result_quality": persisted.get("result_quality"),
                    "run_id": persisted.get("run_id"),
                    "lease_id": persisted.get("lease_id"),
                    "at": updated_at,
                }
            )
            self._write_json(self.snapshot_path, snapshot, updated_at=updated_at)
        return persisted

    def create_task(self, *, site: str, intent: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.locked():
            task_id = self._new_task_id(site, intent, payload)
            task_updated_at = utc_now()
            task = build_task_record(
                task_id=task_id,
                site=site,
                intent=intent,
                payload=payload,
                updated_at=task_updated_at,
            )
            snapshot = self.load_snapshot()
            snapshot["tasks"][task_id] = build_task_snapshot(task)
            self._append_event(build_task_created_event(task=task, at=utc_now()))
            task = self._write_json(self.task_path(task_id), task, updated_at=task_updated_at)
            self._write_json(self.snapshot_path, snapshot)
        return task
