from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# `pytest tests/test_taobao_adapter_contract.py -v` does not place the repo root on sys.path here.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from scripts.adapters import taobao_workflow


def build_args(output_dir: Path, *, count: str) -> argparse.Namespace:
    return argparse.Namespace(output=str(output_dir), count=count, task_id="task-123")


def test_write_contract_outputs_writes_contract_files_under_stable_path(tmp_path: Path) -> None:
    records = [{"rank": 1, "title": "儿童童书", "url": "https://example.com/item/1"}]

    taobao_workflow.write_contract_outputs(
        records=records,
        output_dir=tmp_path,
        task_id="task-123",
        site="taobao",
        intent="search",
        requested_count=20,
        warnings=[],
        needs_user_action=False,
    )

    summary = json.loads((tmp_path / "contract" / "summary.json").read_text(encoding="utf-8"))
    progress = json.loads((tmp_path / "contract" / "progress.json").read_text(encoding="utf-8"))
    results = json.loads((tmp_path / "contract" / "artifacts" / "results.json").read_text(encoding="utf-8"))

    assert summary["schema_version"] == 1
    assert summary["task_id"] == "task-123"
    assert summary["site"] == "taobao"
    assert summary["requested_count"] == 20
    assert summary["collected_count"] == 1
    assert summary["artifacts"] == ["contract/artifacts/results.json"]
    assert progress["schema_version"] == 1
    assert progress["task_id"] == "task-123"
    assert progress["stage"] == "writing_results"
    assert results == records


def test_finish_preserves_legacy_records_summary_and_writes_contract_summary(tmp_path: Path) -> None:
    records = [{"rank": 1, "title": "儿童童书", "url": "https://example.com/item/1"}]

    exit_code = taobao_workflow.finish(
        records,
        build_args(tmp_path, count="20"),
        "search",
        "淘宝搜索: 儿童童书",
    )

    legacy_summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    contract_summary = json.loads((tmp_path / "contract" / "summary.json").read_text(encoding="utf-8"))
    contract_results = json.loads((tmp_path / "contract" / "artifacts" / "results.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert legacy_summary == records
    assert contract_summary["task_id"] == "task-123"
    assert contract_summary["site"] == "taobao"
    assert contract_summary["intent"] == "search"
    assert contract_summary["requested_count"] == 20
    assert contract_summary["collected_count"] == 1
    assert contract_results == records


def test_finish_uses_single_item_requested_count_for_detail_even_with_invalid_count(tmp_path: Path) -> None:
    records = [{"field": "商品名称", "value": "儿童童书"}]

    taobao_workflow.finish(
        records,
        build_args(tmp_path, count="invalid"),
        "detail",
        "淘宝商品详情: 827563850178",
    )

    contract_summary = json.loads((tmp_path / "contract" / "summary.json").read_text(encoding="utf-8"))
    contract_progress = json.loads((tmp_path / "contract" / "progress.json").read_text(encoding="utf-8"))

    assert contract_summary["task_id"] == "task-123"
    assert contract_summary["intent"] == "detail"
    assert contract_summary["requested_count"] == 1
    assert contract_progress["task_id"] == "task-123"
    assert contract_progress["requested_items"] == 1


def test_build_parser_accepts_task_id_contract_argument() -> None:
    parser = taobao_workflow.build_parser()

    args = parser.parse_args(
        [
            "search",
            "view",
            "--task-id",
            "task-123",
            "--session",
            "s1",
            "--tab",
            "t1",
            "--output",
            "/tmp/out",
            "--count",
            "20",
            "--query",
            "儿童童书",
        ]
    )

    assert args.task_id == "task-123"
