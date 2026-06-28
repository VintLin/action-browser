from pathlib import Path
import sys

# `pytest tests/test_scheduler_state.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.scheduler_lib.state import SchedulerStore, sanitize_id


def test_sanitize_id_matches_run_style() -> None:
    assert sanitize_id(" taobao/search:儿童童书 ") == "taobao_search_儿童童书"


def test_store_writes_schema_and_snapshot(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    task = store.create_task(site="taobao", intent="search", payload={"query": "儿童童书", "limit": 20})

    snapshot = store.load_snapshot()

    assert snapshot["schema_version"] == 1
    assert task["status"] == "queued"
    assert (tmp_path / "state.json").exists()
    assert (tmp_path / "tasks" / f"{task['task_id']}.json").exists()


def test_store_appends_event_before_snapshot(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    task = store.create_task(site="taobao", intent="search", payload={"query": "儿童童书"})
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) >= 1
    assert '"event_type": "task_created"' in lines[0]
    assert task["task_id"] in lines[0]
