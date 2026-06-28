from pathlib import Path
import sys

# `pytest tests/test_scheduler_cli.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts import scheduler


def test_submit_creates_task_and_prints_id(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))

    assert (
        scheduler.main(
            ["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书", "--limit", "20"]
        )
        == 0
    )

    out = capsys.readouterr().out
    assert "task_id" in out
    assert (tmp_path / "state.json").exists()


def test_list_shows_queued_task(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ACTION_BROWSER_SCHEDULER_DIR", str(tmp_path))
    scheduler.main(["submit", "--site", "taobao", "--intent", "search", "--query", "儿童童书"])

    assert scheduler.main(["list"]) == 0

    assert "queued" in capsys.readouterr().out
