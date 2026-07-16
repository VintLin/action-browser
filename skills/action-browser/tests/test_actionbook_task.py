from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import actionbook_task


def test_task_runner_acquires_exports_and_releases(monkeypatch) -> None:
    events: list[object] = []

    monkeypatch.setattr(
        actionbook_task,
        "acquire_task_tab",
        lambda args: {
            "task_id": args.task,
            "session_id": "shared",
            "tab_id": "t7",
        },
    )
    monkeypatch.setattr(
        actionbook_task,
        "release_task_tab",
        lambda args: events.append(("release", args.task)) or {"status": "released"},
    )

    def fake_run(command, *, cwd, env, check):
        events.append(
            (
                "run",
                command,
                cwd,
                env["ACTIONBOOK_TASK_ID"],
                env["ACTIONBOOK_SESSION_ID"],
                env["ACTIONBOOK_TAB_ID"],
                check,
            )
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(actionbook_task.subprocess, "run", fake_run)

    assert actionbook_task.main(
        [
            "--task",
            "research-a",
            "--session",
            "shared",
            "--url",
            "https://example.com",
            "--cwd",
            "/tmp",
            "--",
            "python3",
            "workflow.py",
        ]
    ) == 0
    assert events == [
        (
            "run",
            ["python3", "workflow.py"],
            "/tmp",
            "research-a",
            "shared",
            "t7",
            False,
        ),
        ("release", "research-a"),
    ]


def test_task_runner_releases_after_child_failure(monkeypatch) -> None:
    released: list[str] = []
    monkeypatch.setattr(
        actionbook_task,
        "acquire_task_tab",
        lambda args: {"task_id": args.task, "session_id": "s1", "tab_id": "t1"},
    )
    monkeypatch.setattr(
        actionbook_task,
        "release_task_tab",
        lambda args: released.append(args.task) or {"status": "released"},
    )
    monkeypatch.setattr(
        actionbook_task.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 7),
    )

    assert actionbook_task.main(["--task", "research-b", "--", "false"]) == 7
    assert released == ["research-b"]


def test_task_runner_preserves_existing_environment(monkeypatch) -> None:
    captured: dict[str, str] = {}
    monkeypatch.setenv("EXISTING_VALUE", "kept")
    monkeypatch.setattr(
        actionbook_task,
        "acquire_task_tab",
        lambda args: {"task_id": args.task, "session_id": "s1", "tab_id": "t1"},
    )
    monkeypatch.setattr(actionbook_task, "release_task_tab", lambda args: {"status": "released"})

    def fake_run(command, *, cwd, env, check):
        captured.update(env)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(actionbook_task.subprocess, "run", fake_run)

    assert actionbook_task.main(["--task", "research-c", "--", "true"]) == 0
    assert captured["EXISTING_VALUE"] == "kept"
    assert captured["ACTIONBOOK_TASK_ID"] == "research-c"
    assert captured["ACTIONBOOK_SESSION_ID"] == "s1"
    assert captured["ACTIONBOOK_TAB_ID"] == "t1"
    assert os.environ.get("ACTIONBOOK_TASK_ID") != "research-c"
