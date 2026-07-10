from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.scheduler_lib.contracts import (
    STATUS_BLOCKED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_WAITING_USER,
    STAGE_USING_BROWSER,
    STAGE_WAITING_USER_ACTION,
    apply_summary_result,
    set_task_status,
)


def resolve_output_dir(task: dict[str, Any]) -> Path | None:
    for key in ("output_dir", "output", "artifacts_dir"):
        value = str(task.get(key) or "").strip()
        if value:
            return Path(value).expanduser()
    return None


def resolve_summary_path(task: dict[str, Any]) -> Path | None:
    output_dir = resolve_output_dir(task)
    if output_dir is None:
        return None
    contract_summary = output_dir / "contract" / "summary.json"
    if contract_summary.exists():
        return contract_summary
    return output_dir / "summary.json"


def resolve_progress_path(task: dict[str, Any], scheduler_root: Path) -> Path:
    output_dir = resolve_output_dir(task)
    if output_dir is not None:
        contract_progress = output_dir / "contract" / "progress.json"
        if contract_progress.exists():
            return contract_progress
    return Path(scheduler_root) / "progress" / f"{task['task_id']}.json"


def _load_json_dict(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path or not path.exists():
        return None, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "invalid"
    if not isinstance(payload, dict):
        return None, "invalid"
    return payload, None


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _snapshot_is_fresh(snapshot: dict[str, Any], now: datetime, ttl_seconds: int) -> bool:
    timestamp = (
        _parse_timestamp(snapshot.get("updated_at"))
        or _parse_timestamp(snapshot.get("last_progress_at"))
        or _parse_timestamp(snapshot.get("last_heartbeat_at"))
    )
    if timestamp is None:
        # ponytail: old adapters may not timestamp progress yet; keep the explicit status usable.
        return True
    return now - timestamp <= timedelta(seconds=ttl_seconds)


def reconcile_task_state(
    task: dict[str, Any],
    *,
    run_state: dict[str, Any] | None,
    tab_alive: bool,
    summary_path: Path | None,
    progress_path: Path | None = None,
    output_dir: Path | None = None,
    now: datetime | None = None,
    freshness_ttl_seconds: int = 30,
    waiting_user_hold_seconds: int = 900,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    summary, summary_error = _load_json_dict(summary_path) if summary_path else (None, None)
    progress, progress_error = _load_json_dict(progress_path) if progress_path else (None, None)

    if run_state and run_state.get("status") == STATUS_RUNNING and tab_alive:
        if (
            isinstance(progress, dict)
            and str(progress.get("status") or "") == STATUS_WAITING_USER
            and _snapshot_is_fresh(progress, current_time, waiting_user_hold_seconds)
        ):
            return set_task_status(
                task,
                status=STATUS_WAITING_USER,
                stage=STAGE_WAITING_USER_ACTION,
                reason_code=progress.get("reason_code"),
            )
        stage = task.get("stage") or STAGE_USING_BROWSER
        if isinstance(progress, dict) and _snapshot_is_fresh(progress, current_time, freshness_ttl_seconds):
            stage = progress.get("stage") or stage
        return set_task_status(task, status=STATUS_RUNNING, stage=stage)

    if isinstance(summary, dict):
        return apply_summary_result(task, summary)

    if run_state and run_state.get("status") == STATUS_RUNNING and not tab_alive:
        return set_task_status(task, status=STATUS_FAILED, reason_code="tab_lost")

    if summary_error == "invalid":
        return set_task_status(task, status=STATUS_BLOCKED, reason_code="summary_invalid")

    if (
        isinstance(progress, dict)
        and str(progress.get("status") or "") == STATUS_WAITING_USER
        and _snapshot_is_fresh(progress, current_time, waiting_user_hold_seconds)
    ):
        return set_task_status(
            task,
            status=STATUS_WAITING_USER,
            stage=STAGE_WAITING_USER_ACTION,
            reason_code=progress.get("reason_code"),
        )

    if progress_error == "invalid":
        return set_task_status(task, status=STATUS_BLOCKED, reason_code="progress_invalid")

    if (progress_path and progress_path.exists()) or (output_dir and output_dir.exists()):
        return set_task_status(task, status=STATUS_BLOCKED, reason_code="summary_missing")

    return set_task_status(task, status=STATUS_BLOCKED, reason_code="run_missing")
