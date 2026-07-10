from __future__ import annotations

import json
import os
from pathlib import Path


def _require(payload: dict[str, object], fields: set[str], name: str) -> None:
    if not isinstance(payload, dict) or not fields.issubset(payload) or payload.get("schema_version") != 1:
        raise ValueError(f"invalid {name}")


def validate_result_envelope(payload: dict[str, object]) -> None:
    _require(payload, {"schema_version", "run_id", "task_id", "capability_id", "site", "command", "status", "result_quality", "contract_ref", "artifact_refs", "strategy_used", "fallback_reason", "failure", "started_at", "finished_at"}, "result envelope")


def validate_adapter_contract(payload: dict[str, object]) -> None:
    _require(payload, {"schema_version", "run_id", "task_id", "capability_id", "site", "status", "artifacts", "failure", "ok", "reason_code"}, "adapter contract")


def validate_download_manifest(payload: dict[str, object]) -> None:
    _require(payload, {"schema_version", "items"}, "download manifest")
    if not isinstance(payload["items"], list) or any(not isinstance(item, dict) or not {"status", "size", "checksum"}.issubset(item) for item in payload["items"]):
        raise ValueError("invalid download manifest")


def write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as output:
        output.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        output.flush()
        os.fsync(output.fileno())
    tmp.replace(path)
