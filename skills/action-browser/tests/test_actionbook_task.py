from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


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


def test_task_runner_releases_after_sigterm(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    released = tmp_path / "released"
    pid = os.fork()
    if pid == 0:
        os.setsid()

        def acquire(args):
            ready.write_text("ready", encoding="utf-8")
            return {
                "task_id": args.task,
                "session_id": "s1",
                "tab_id": "t1",
                "status": "acquired",
            }

        actionbook_task.acquire_task_tab = acquire
        actionbook_task.release_task_tab = lambda args: released.write_text(args.task, encoding="utf-8")
        code = actionbook_task.main(
            ["--task", "signal-test", "--", sys.executable, "-c", "import time; time.sleep(30)"]
        )
        os._exit(code)

    deadline = time.monotonic() + 5.0
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists()

    os.killpg(pid, signal.SIGTERM)
    _, status = os.waitpid(pid, 0)

    assert os.WIFEXITED(status)
    assert os.WEXITSTATUS(status) == 130
    assert released.read_text(encoding="utf-8") == "signal-test"


def test_task_runner_refuses_to_reuse_existing_tab(monkeypatch, capsys) -> None:
    released: list[str] = []
    monkeypatch.setattr(
        actionbook_task,
        "acquire_task_tab",
        lambda args: {
            "task_id": args.task,
            "session_id": "s1",
            "tab_id": "t1",
            "status": "reused",
        },
    )
    monkeypatch.setattr(
        actionbook_task,
        "release_task_tab",
        lambda args: released.append(args.task),
    )
    monkeypatch.setattr(
        actionbook_task.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("existing task tab must not run a second workflow"),
    )

    assert actionbook_task.main(["--task", "research-active", "--", "true"]) == 2
    assert "already owns a live tab" in capsys.readouterr().err
    assert released == []
