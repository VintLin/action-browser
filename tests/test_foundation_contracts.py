from pathlib import Path
import json

import pytest

from scripts.foundation_contracts import validate_adapter_contract, validate_download_manifest, validate_result_envelope, validate_site_artifact, write_json_atomic
from scripts.scheduler_lib.contracts import STATUS_FAILED, STATUS_RUNNING, apply_summary_result, build_task_record


def test_shared_contract_validators_reject_missing_required_fields() -> None:
    with pytest.raises(ValueError):
        validate_result_envelope({"schema_version": 1})
    with pytest.raises(ValueError):
        validate_adapter_contract({"schema_version": 1})
    with pytest.raises(ValueError):
        validate_download_manifest({"schema_version": 1, "items": [{}]})


def test_shared_contract_validators_reject_wrong_field_types() -> None:
    with pytest.raises(ValueError):
        validate_result_envelope({key: 1 for key in ("schema_version", "run_id", "task_id", "capability_id", "site", "command", "status", "result_quality", "contract_ref", "artifact_refs", "strategy_used", "fallback_reason", "failure", "started_at", "finished_at")})
    with pytest.raises(ValueError):
        validate_adapter_contract({key: 1 for key in ("schema_version", "run_id", "task_id", "capability_id", "site", "status", "artifacts", "failure", "ok", "reason_code")})
    with pytest.raises(ValueError):
        validate_site_artifact({"schema_version": 1, "capability_id": "x", "items": {}})


def test_atomic_json_writer_replaces_without_partial_file(tmp_path: Path) -> None:
    path = tmp_path / "contract.json"
    write_json_atomic(path, {"schema_version": 1, "value": "ok"})
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert not list(tmp_path.glob("*.tmp"))


def test_shared_schema_artifacts_are_versioned_json() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas" / "contracts"
    for path in root.glob("*.schema.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["$schema"].endswith("schema")


def test_retryable_failure_returns_running_retry_state() -> None:
    task = build_task_record(task_id="t", site="x", intent="read", payload={}, updated_at="now")
    result = apply_summary_result(task, {"ok": False, "needs_user_action": False, "status": STATUS_FAILED, "reason_code": "timeout", "failure": {"retryable": True}, "collected_count": 0, "requested_count": 1})
    assert result["status"] == STATUS_RUNNING
    assert result["stage"] == "retrying"
