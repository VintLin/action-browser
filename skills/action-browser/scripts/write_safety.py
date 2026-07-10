from __future__ import annotations

import hashlib
import json


class WriteSafetyError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def preview_hash(capability_id: str, payload: dict[str, object]) -> str:
    """Bind a later write approval to a stable, exact mutation preview."""
    encoded = json.dumps({"capability_id": capability_id, "payload": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def require_preview_hash(execute: bool, supplied_hash: str, expected_hash: str) -> None:
    if not execute:
        raise WriteSafetyError("execute_required")
    if not supplied_hash:
        raise WriteSafetyError("preview_hash_required")
    if supplied_hash != expected_hash:
        raise WriteSafetyError("preview_hash_mismatch")


def retry_policy(idempotency: str, outcome_known: bool) -> str:
    if outcome_known:
        return "no_retry"
    return "verify_before_retry" if idempotency == "verify_before_retry" else "stop_for_user"
