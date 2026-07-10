import pytest

from scripts.write_safety import WriteSafetyError, preview_hash, require_preview_hash, retry_policy


def test_preview_hash_is_order_independent_and_payload_bound() -> None:
    assert preview_hash("chatgpt.ask.create", {"text": "draft", "max_actions": 1}) == preview_hash("chatgpt.ask.create", {"max_actions": 1, "text": "draft"})
    assert preview_hash("chatgpt.ask.create", {"text": "draft"}) != preview_hash("chatgpt.ask.create", {"text": "changed"})


def test_uncertain_writes_do_not_blindly_retry() -> None:
    assert retry_policy("verify_before_retry", False) == "verify_before_retry"
    assert retry_policy("not_applicable", False) == "stop_for_user"
    assert retry_policy("verify_before_retry", True) == "no_retry"


def test_execute_gate_requires_exact_preview_hash() -> None:
    with pytest.raises(WriteSafetyError, match="preview_hash_required"):
        require_preview_hash(True, "", "expected")
    with pytest.raises(WriteSafetyError, match="preview_hash_mismatch"):
        require_preview_hash(True, "wrong", "expected")
    require_preview_hash(True, "expected", "expected")
