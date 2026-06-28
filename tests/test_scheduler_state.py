from pathlib import Path
import sys
import json

import pytest

# `pytest tests/test_scheduler_state.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.scheduler_lib.state import SchedulerStore, sanitize_id


def test_sanitize_id_matches_run_style() -> None:
    assert sanitize_id(" taobao/search:儿童童书 ") == "taobao_search_儿童童书"


def test_sanitize_id_empty_input_raises() -> None:
    with pytest.raises(ValueError, match="empty after sanitization"):
        sanitize_id(" ._- ")


def test_store_writes_schema_and_snapshot(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    task = store.create_task(site="taobao", intent="search", payload={"query": "儿童童书", "limit": 20})

    snapshot = store.load_snapshot()

    assert snapshot["schema_version"] == 1
    assert task["status"] == "queued"
    assert snapshot["tasks"][task["task_id"]] == {"status": "queued", "stage": "triaging"}
    assert (tmp_path / "state.json").exists()
    assert (tmp_path / "tasks" / f"{task['task_id']}.json").exists()


def test_duplicate_create_task_calls_produce_distinct_task_ids(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)

    first = store.create_task(site="taobao", intent="search", payload={"query": "儿童童书"})
    second = store.create_task(site="taobao", intent="search", payload={"query": "儿童童书"})

    assert first["task_id"] != second["task_id"]
    assert first["task_id"].startswith("taobao_search_儿童童书")
    assert second["task_id"].startswith("taobao_search_儿童童书")


def test_store_event_includes_lifecycle_fields(tmp_path: Path) -> None:
    store = SchedulerStore(tmp_path)
    task = store.create_task(site="taobao", intent="search", payload={"query": "儿童童书"})
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    event = json.loads(lines[0])

    assert len(lines) >= 1
    assert event["event_type"] == "task_created"
    assert event["task_id"] == task["task_id"]
    assert event["status"] == task["status"]
    assert event["stage"] == task["stage"]
