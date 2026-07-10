from __future__ import annotations

import json
import os
from pathlib import Path

RESULT_ENVELOPE_FIELDS = {"schema_version", "run_id", "task_id", "capability_id", "site", "command", "status", "result_quality", "contract_ref", "artifact_refs", "strategy_used", "fallback_reason", "failure", "started_at", "finished_at"}
ADAPTER_CONTRACT_FIELDS = {"schema_version", "run_id", "task_id", "reference_baseline", "execution_baseline", "capability_id", "site", "status", "stage", "result_quality", "requested_count", "collected_count", "access", "strategy_used", "fallback_reason", "limits", "artifacts", "warnings", "failure", "progress", "started_at", "updated_at", "finished_at", "ok", "needs_user_action", "reason_code"}
DOWNLOAD_MANIFEST_FIELDS = {"schema_version", "subject_id", "max_item_bytes", "max_total_bytes", "items"}


def _require(payload: dict[str, object], fields: set[str], name: str) -> None:
    if not isinstance(payload, dict) or set(payload) != fields or payload.get("schema_version") != 1:
        raise ValueError(f"invalid {name}")


def validate_result_envelope(payload: dict[str, object]) -> None:
    _require(payload, RESULT_ENVELOPE_FIELDS, "result envelope")
    failure = payload["failure"]
    if not all(isinstance(payload[key], str) for key in ("run_id", "task_id", "capability_id", "site", "command", "status", "result_quality", "strategy_used", "started_at", "finished_at")) or not isinstance(payload["artifact_refs"], list) or not all(isinstance(item, str) for item in payload["artifact_refs"]) or payload["contract_ref"] is not None and not isinstance(payload["contract_ref"], str) or payload["fallback_reason"] is not None and not isinstance(payload["fallback_reason"], str) or failure is not None and (not isinstance(failure, dict) or not isinstance(failure.get("reason_code"), str) or not isinstance(failure.get("message"), str) or not isinstance(failure.get("retryable"), bool)):
        raise ValueError("invalid result envelope")


def validate_adapter_contract(payload: dict[str, object]) -> None:
    _require(payload, ADAPTER_CONTRACT_FIELDS, "adapter contract")
    failure = payload["failure"]
    if (
        not all(isinstance(payload[key], str) for key in ("run_id", "task_id", "reference_baseline", "execution_baseline", "capability_id", "site", "status", "stage", "result_quality", "access", "strategy_used", "started_at", "updated_at", "finished_at"))
        or not isinstance(payload["requested_count"], int)
        or not isinstance(payload["collected_count"], int)
        or not isinstance(payload["limits"], dict)
        or not isinstance(payload["artifacts"], list)
        or not all(isinstance(item, str) for item in payload["artifacts"])
        or not isinstance(payload["warnings"], list)
        or not all(isinstance(item, str) for item in payload["warnings"])
        or not isinstance(payload["progress"], dict)
        or not isinstance(payload["ok"], bool)
        or not isinstance(payload["needs_user_action"], bool)
        or payload["fallback_reason"] is not None and not isinstance(payload["fallback_reason"], str)
        or payload["reason_code"] is not None and not isinstance(payload["reason_code"], str)
        or failure is not None and (not isinstance(failure, dict) or set(failure) != {"reason_code", "message", "retryable"} or not isinstance(failure["reason_code"], str) or not isinstance(failure["message"], str) or not isinstance(failure["retryable"], bool))
    ):
        raise ValueError("invalid adapter contract")


def validate_site_artifact(payload: dict[str, object]) -> None:
    _require(payload, {"schema_version", "capability_id", "items"}, "site artifact")
    if not isinstance(payload["capability_id"], str) or not isinstance(payload["items"], list):
        raise ValueError("invalid site artifact")


def validate_download_manifest(payload: dict[str, object]) -> None:
    _require(payload, DOWNLOAD_MANIFEST_FIELDS, "download manifest")
    if not isinstance(payload["items"], list) or any(not isinstance(item, dict) or not {"status", "size", "checksum"}.issubset(item) or not isinstance(item["status"], str) or not isinstance(item["size"], int) or not isinstance(item["checksum"], str) for item in payload["items"]):
        raise ValueError("invalid download manifest")


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as output:
        output.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    tmp.replace(path)
