from __future__ import annotations

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

from scripts import taobao_workflow


def test_write_contract_outputs(tmp_path: Path) -> None:
    records = [{"rank": 1, "title": "儿童童书", "url": "https://example.com/item/1"}]

    taobao_workflow.write_contract_outputs(
        records=records,
        output_dir=tmp_path,
        site="taobao",
        intent="search",
        requested_count=20,
        warnings=[],
        needs_user_action=False,
    )

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    progress = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))

    assert summary["site"] == "taobao"
    assert summary["requested_count"] == 20
    assert summary["collected_count"] == 1
    assert progress["stage"] == "writing_results"
