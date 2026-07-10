from pathlib import Path
import json

import pytest

from scripts.foundation_contracts import validate_adapter_contract, validate_download_manifest, validate_result_envelope, validate_site_artifact, write_json_atomic
from scripts.scheduler_lib.contracts import STATUS_FAILED, STATUS_RUNNING, apply_summary_result, build_task_record


def valid_result_envelope() -> dict[str, object]:
    return {"schema_version": 1, "run_id": "run", "task_id": "task", "capability_id": "site.read", "site": "site", "command": "run", "status": "completed", "result_quality": "full", "contract_ref": None, "artifact_refs": [], "strategy_used": "public_http", "fallback_reason": None, "failure": None, "started_at": "now", "finished_at": "now"}


def valid_adapter_contract() -> dict[str, object]:
    return {"schema_version": 1, "run_id": "run", "task_id": "task", "reference_baseline": "reference", "execution_baseline": "execution", "capability_id": "site.read", "site": "site", "status": "completed", "stage": "completed", "result_quality": "full", "requested_count": 1, "collected_count": 1, "access": "public", "strategy_used": "public_http", "fallback_reason": None, "limits": {}, "artifacts": [], "warnings": [], "failure": None, "progress": {"schema_version": 1, "task_id": "task", "status": "completed", "stage": "completed", "completed": 1, "requested": 1, "last_url": "https://example.test", "last_title": "Example"}, "started_at": "now", "updated_at": "now", "finished_at": "now", "ok": True, "needs_user_action": False, "reason_code": None}


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


def test_shared_contract_validators_reject_unknown_and_invalid_nullable_fields() -> None:
    envelope = valid_result_envelope()
    envelope["unexpected"] = True
    with pytest.raises(ValueError):
        validate_result_envelope(envelope)
    envelope = valid_result_envelope()
    envelope["contract_ref"] = 1
    with pytest.raises(ValueError):
        validate_result_envelope(envelope)

    contract = valid_adapter_contract()
    contract["unexpected"] = True
    with pytest.raises(ValueError):
        validate_adapter_contract(contract)
    contract = valid_adapter_contract()
    contract["reason_code"] = False
    with pytest.raises(ValueError):
        validate_adapter_contract(contract)
    contract = valid_adapter_contract()
    contract["fallback_reason"] = False
    with pytest.raises(ValueError):
        validate_adapter_contract(contract)
    contract = valid_adapter_contract()
    contract["failure"] = {"reason_code": "failed", "message": "failure", "retryable": "no"}
    with pytest.raises(ValueError):
        validate_adapter_contract(contract)


def test_atomic_json_writer_replaces_without_partial_file(tmp_path: Path) -> None:
    path = tmp_path / "contract.json"
    write_json_atomic(path, {"schema_version": 1, "value": "ok"})
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert not list(tmp_path.glob("*.tmp"))


def test_shared_schema_artifacts_are_versioned_json() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas" / "contracts"
    for path in root.glob("*.schema.json"):
        assert json.loads(path.read_text(encoding="utf-8"))["$schema"].endswith("schema")


def test_adapter_contract_schema_is_strict_and_declares_shared_fields() -> None:
    path = Path(__file__).resolve().parents[1] / "schemas" / "contracts" / "adapter-contract.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(valid_adapter_contract())


def test_retryable_failure_returns_running_retry_state() -> None:
    task = build_task_record(task_id="t", site="x", intent="read", payload={}, updated_at="now")
    result = apply_summary_result(task, {"ok": False, "needs_user_action": False, "status": STATUS_FAILED, "reason_code": "timeout", "failure": {"retryable": True}, "collected_count": 0, "requested_count": 1})
    assert result["status"] == STATUS_RUNNING
    assert result["stage"] == "retrying"
