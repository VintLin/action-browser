from __future__ import annotations

import json
from pathlib import Path
import sys

# `pytest tests/test_scheduler_reconcile.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.scheduler_lib.reconcile import reconcile_task_state


def write_summary(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_reconcile_keeps_running_when_run_and_tab_are_alive(tmp_path: Path) -> None:
    task = {"task_id": "t1", "status": "queued", "reason_code": "old_failure"}

    result = reconcile_task_state(
        task,
        run_state={"status": "running"},
        tab_alive=True,
        summary_path=tmp_path / "summary.json",
    )

    assert result["status"] == "running"
    assert result["stage"] == "using_browser"
    assert result["reason_code"] is None


def test_reconcile_marks_completed_partial_from_summary(tmp_path: Path) -> None:
    task = {"task_id": "t1", "status": "running"}

    result = reconcile_task_state(
        task,
        run_state=None,
        tab_alive=False,
        summary_path=write_summary(
            tmp_path / "summary.json",
            {
                "ok": True,
                "needs_user_action": False,
                "requested_count": 20,
                "collected_count": 8,
            },
        ),
    )

    assert result["status"] == "completed"
    assert result["result_quality"] == "partial"


def test_reconcile_marks_completed_full_from_summary(tmp_path: Path) -> None:
    task = {"task_id": "t1", "status": "running"}

    result = reconcile_task_state(
        task,
        run_state=None,
        tab_alive=False,
        summary_path=write_summary(
            tmp_path / "summary.json",
            {
                "ok": True,
                "needs_user_action": False,
                "requested_count": 20,
                "collected_count": 20,
            },
        ),
    )

    assert result["status"] == "completed"
    assert result["result_quality"] == "full"


def test_reconcile_marks_waiting_user_when_summary_requires_it(tmp_path: Path) -> None:
    task = {"task_id": "t1", "status": "running", "result_quality": "full"}

    result = reconcile_task_state(
        task,
        run_state=None,
        tab_alive=False,
        summary_path=write_summary(
            tmp_path / "summary.json",
            {
                "ok": True,
                "needs_user_action": True,
                "requested_count": 20,
                "collected_count": 8,
                "reason_code": "needs_login",
            },
        ),
    )

    assert result["status"] == "waiting_user"
    assert result["reason_code"] == "needs_login"
    assert result["result_quality"] is None


def test_reconcile_marks_failed_when_summary_reports_not_ok(tmp_path: Path) -> None:
    task = {"task_id": "t1", "status": "running", "result_quality": "partial"}

    result = reconcile_task_state(
        task,
        run_state=None,
        tab_alive=False,
        summary_path=write_summary(
            tmp_path / "summary.json",
            {
                "ok": False,
                "needs_user_action": False,
                "requested_count": 20,
                "collected_count": 0,
                "reason_code": "site_error",
            },
        ),
    )

    assert result["status"] == "failed"
    assert result["reason_code"] == "site_error"
    assert result["result_quality"] is None


def test_reconcile_marks_blocked_when_run_missing_and_no_summary(tmp_path: Path) -> None:
    task = {
        "task_id": "t1",
        "status": "running",
        "run_id": "run-1",
        "lease_id": "lease-1",
    }
    result = reconcile_task_state(task, run_state=None, tab_alive=False, summary_path=tmp_path / "summary.json")

    assert result["status"] == "blocked"
    assert result["reason_code"] == "run_missing"
