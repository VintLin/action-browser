from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

# `pytest tests/test_scheduler_cli.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import scheduler


def parse_json_output(text: str) -> dict[str, object]:
    return json.loads(text)


def test_script_entrypoint_submit_from_repo_root(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["ACTION_BROWSER_SCHEDULER_DIR"] = str(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/scheduler.py",
            "submit",
            "--site",
            "taobao",
            "--intent",
            "search",
            "--query",
            "儿童童书",
            "--limit",
            "20",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0
    assert parse_json_output(completed.stdout)["task_id"]
    assert (tmp_path / "state.json").exists()


def test_submit_creates_task_and_prints_id(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))

    assert (
        scheduler.main(
            ["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书", "--limit", "20"]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert parse_json_output(out)["task_id"]
    assert (tmp_path / "state.json").exists()


def test_submit_rejects_non_positive_limit(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))

    assert (
        scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书", "--limit", "0"])
        != 0
    )

    payload = parse_json_output(capsys.readouterr().out)
    assert payload["error"] == "invalid_limit"
    assert not (tmp_path / "state.json").exists()


def test_list_shows_queued_task(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书"])

    assert scheduler.main(["list"]) == 0

    assert "queued" in capsys.readouterr().out


def test_status_returns_submitted_task_record(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书", "--limit", "20"])
    task_id = next(iter(json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["tasks"].keys()))
    capsys.readouterr()

    assert scheduler.main(["status", "--task", task_id]) == 0

    payload = parse_json_output(capsys.readouterr().out)
    assert payload["task_id"] == task_id
    assert payload["site"] == "taobao"
    assert payload["intent"] == "search"
    assert payload["status"] == "queued"
    assert payload["payload"] == {"query": "儿童童书", "limit": 20}


def test_status_missing_task_returns_controlled_error(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))

    assert scheduler.main(["status", "--task", "missing-task"]) == 1

    payload = parse_json_output(capsys.readouterr().out)
    assert payload["error"] == "task_not_found"
    assert payload["task_id"] == "missing-task"


def test_stop_delegates_to_actionbook_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(scheduler, "call_actionbook_run", fake_run)
    monkeypatch.setattr(scheduler, "has_tracked_run", lambda run_id: True)
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书"])
    task_id = next(iter(json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["tasks"].keys()))

    assert scheduler.main(["stop", "--task", task_id]) == 0
    assert calls and calls[0][:2] == ["stop", "--id"]
    assert calls[0][2] == task_id


def test_stop_prefers_persisted_run_id_over_task_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> int:
        calls.append(args)
        return 0

    monkeypatch.setattr(scheduler, "call_actionbook_run", fake_run)
    monkeypatch.setattr(scheduler, "has_tracked_run", lambda run_id: True)
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书"])
    task_id = next(iter(json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["tasks"].keys()))
    task_path = tmp_path / "tasks" / f"{task_id}.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task["run_id"] = "run-123"
    task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    assert scheduler.main(["stop", "--task", task_id]) == 0
    assert calls == [["stop", "--id", "run-123"]]


def test_stop_returns_controlled_error_when_run_is_not_tracked(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))

    def fail_if_called(_args: list[str]) -> int:
        raise AssertionError("delegated stop should not be called when no tracked run exists")

    monkeypatch.setattr(scheduler, "call_actionbook_run", fail_if_called)
    monkeypatch.setattr(scheduler, "has_tracked_run", lambda run_id: False)
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书"])
    task_id = next(iter(json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["tasks"].keys()))
    capsys.readouterr()

    assert scheduler.main(["stop", "--task", task_id]) == 1
    payload = parse_json_output(capsys.readouterr().out)
    assert payload == {"error": "run_not_found", "task_id": task_id, "run_id": task_id}


def test_stop_normalizes_missing_run_reported_by_delegate(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))

    def fake_run(args: list[str]) -> int:
        print(json.dumps({"run_id": args[2], "status": "missing"}))
        return 0

    monkeypatch.setattr(scheduler, "call_actionbook_run", fake_run)
    monkeypatch.setattr(scheduler, "has_tracked_run", lambda run_id: True)
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书"])
    task_id = next(iter(json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["tasks"].keys()))
    capsys.readouterr()

    assert scheduler.main(["stop", "--task", task_id]) == 1
    payload = parse_json_output(capsys.readouterr().out)
    assert payload == {"error": "run_not_found", "task_id": task_id, "run_id": task_id}


def test_reconcile_reports_unimplemented(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))

    assert scheduler.main(["reconcile"]) == 1
    reconcile_payload = parse_json_output(capsys.readouterr().out)
    assert reconcile_payload["error"] == "not_implemented"
