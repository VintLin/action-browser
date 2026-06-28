from pathlib import Path
import sys

# `pytest tests/test_scheduler_reconcile.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.scheduler_lib.reconcile import reconcile_task_state


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
