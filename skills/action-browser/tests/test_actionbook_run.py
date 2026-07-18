from __future__ import annotations

import json
from pathlib import Path
import signal
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import actionbook_run


def test_main_accepts_argv_for_scheduler_delegation(tmp_path: Path, capsys) -> None:
    assert actionbook_run.main(["--runs-dir", str(tmp_path), "status", "--id", "missing"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "missing"


def test_run_writes_monitor_files_and_mirrors_current_post(tmp_path: Path) -> None:
    progress = tmp_path / "contract" / "progress.json"
    progress.parent.mkdir(parents=True)
    progress.write_text(
        json.dumps(
            {
                "status": "running",
                "stage": "downloading",
                "current_post": "post-001",
                "completed_items": 2,
                "requested_items": 5,
                "updated_at": "2026-07-18T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    assert (
        actionbook_run.main(
            [
                "--runs-dir",
                str(tmp_path / "runs"),
                "run",
                "--id",
                "download-001",
                "--progress-file",
                str(progress),
                "--heartbeat-interval",
                "0.01",
                "--heartbeat-stale-seconds",
                "1",
                "--",
                sys.executable,
                "-c",
                "import time; time.sleep(0.2)",
            ]
        )
        == 0
    )

    state_path = actionbook_run.state_path("download-001", tmp_path / "runs")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["current_post"] == "post-001"
    assert state["completed_items"] == 2
    assert Path(state["heartbeat_file"]).exists()
    assert Path(state["pid_file"]).exists()
    assert Path(state["status_file"]).read_text(encoding="utf-8").strip() == "EXITED"


def test_stop_preserves_graceful_wrapper_exit_when_descendants_need_kill(
    tmp_path: Path, monkeypatch
) -> None:
    path = actionbook_run.state_path("atomic-stop", tmp_path)
    actionbook_run.write_state(
        path,
        {
            "run_id": "atomic-stop",
            "status": "running",
            "pid": 1001,
            "pgid": 1001,
            "exit_code": None,
        },
    )
    monkeypatch.setattr(actionbook_run, "process_alive", lambda _pid: True)

    def terminate_after_wrapper_cleanup(_pgid: int, _grace: float) -> str:
        state = json.loads(path.read_text(encoding="utf-8"))
        state["status"] = "stopped"
        state["exit_code"] = 130
        actionbook_run.write_state(path, state)
        return "killed"

    monkeypatch.setattr(actionbook_run, "terminate_group", terminate_after_wrapper_cleanup)

    result = actionbook_run.stop_one(path, 0.1)
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert result["status"] == "stopped"
    assert result["exit_code"] == 130
    assert result["stop_result"] == "terminated"
    assert result["descendant_stop_result"] == "killed"
    assert persisted["exit_code"] == 130
    assert persisted["stop_result"] == "terminated"
    assert persisted["descendant_stop_result"] == "killed"
    assert persisted["exit_code"] != -signal.SIGKILL
