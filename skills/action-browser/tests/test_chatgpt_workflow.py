import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pytest

from scripts.adapters import chatgpt_workflow
from scripts.adapters.chatgpt_workflow import (
    ChatGptTask,
    WriteSafetyError,
    build_write_preview,
    checkpoint_successes,
    is_nonfatal_submit_error,
    page_has_login_or_risk,
    require_write_approval,
    require_web_search_enabled,
    write_checkpoint,
    submission_record,
)
from scripts.foundation_contracts import validate_adapter_contract, validate_result_envelope


def test_submission_record_tracks_new_chat_defaults() -> None:
    record = submission_record(
        1,
        ChatGptTask(title="Q1", question="Question"),
        "https://chatgpt.com/c/1",
        2,
        "2026-07-02T12:00:00",
        {"search_enabled": True, "search_text": "网页搜索"},
    )

    assert record["mode"] == {
        "surface": "Chat",
        "web_search": True,
        "web_search_state": "网页搜索",
        "intelligence": "极高",
        "model": "latest",
    }


def test_require_web_search_enabled_raises_when_required_but_not_verified() -> None:
    with pytest.raises(RuntimeError, match="web search was required"):
        require_web_search_enabled({"search_enabled": False}, True)


def test_model_settings_failure_is_nonfatal() -> None:
    assert is_nonfatal_submit_error(RuntimeError("model settings control not found: {}"))


def test_research_answer_terms_do_not_trigger_login_detection() -> None:
    state = {
        "href": "https://chatgpt.com/c/1",
        "title": "LLM output verification",
        "text": "Research login and verification limits before adoption.",
    }

    assert not page_has_login_or_risk(state)
    assert page_has_login_or_risk({**state, "text": "Log in to continue"})


def test_ask_defaults_to_dry_run_without_attaching_a_browser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(chatgpt_workflow, "attach_workflow", lambda *_args: pytest.fail("dry-run attached a browser"))

    assert chatgpt_workflow.main(["ask", "--title", "T1", "--question", "Draft", "--output-dir", str(tmp_path)]) == 0

    preview = json.loads(capsys.readouterr().out)
    validate_result_envelope(preview)
    assert preview["status"] == "completed"
    assert preview["capability_id"] == "chatgpt.prompt.message.write"
    assert preview["contract_ref"] == "contract/summary.json"
    contract = json.loads((tmp_path / "contract" / "summary.json").read_text(encoding="utf-8"))
    validate_adapter_contract(contract)
    assert contract["strategy_used"] == "dry_run"
    artifact = json.loads((tmp_path / "artifacts" / "preview.json").read_text(encoding="utf-8"))
    assert artifact["items"][0]["question"] == {"length": 5}
    assert artifact["preview_hash"]


def test_preview_hash_binds_every_material_chatgpt_write_field() -> None:
    task = ChatGptTask(title="T1", question="Draft")
    baseline = build_write_preview("chatgpt.prompt.message.write", [task], require_web_search=False, max_actions=1)

    assert baseline["preview_hash"] != build_write_preview("chatgpt.prompt.message.write", [ChatGptTask(title="T2", question="Draft")], require_web_search=False, max_actions=1)["preview_hash"]
    assert baseline["preview_hash"] != build_write_preview("chatgpt.prompt.message.write", [ChatGptTask(title="T1", question="Changed")], require_web_search=False, max_actions=1)["preview_hash"]
    assert baseline["preview_hash"] != build_write_preview("chatgpt.prompt.message.write", [task], require_web_search=True, max_actions=1)["preview_hash"]
    assert baseline["preview_hash"] != build_write_preview("chatgpt.prompt.message.write", [task], require_web_search=False, max_actions=2)["preview_hash"]


def test_execute_requires_the_matching_preview_hash() -> None:
    preview = build_write_preview("chatgpt.prompt.message.write", [ChatGptTask(title="T1", question="Draft")], require_web_search=False, max_actions=1)

    with pytest.raises(WriteSafetyError, match="preview_hash_required"):
        require_write_approval(True, "", str(preview["preview_hash"]))
    with pytest.raises(WriteSafetyError, match="preview_hash_mismatch"):
        require_write_approval(True, "wrong", str(preview["preview_hash"]))


def test_batch_limit_and_checkpoint_prevent_replay(tmp_path: Path) -> None:
    tasks = [ChatGptTask(title="T1", question="One"), ChatGptTask(title="T2", question="Two")]
    preview = build_write_preview("chatgpt.prompt-batch.message.write", tasks, require_web_search=False, max_actions=2)
    write_checkpoint(tmp_path / "checkpoint.json", str(preview["preview_hash"]), ["1"])

    assert checkpoint_successes(tmp_path / "checkpoint.json", str(preview["preview_hash"])) == {"1"}
    with pytest.raises(WriteSafetyError, match="max_actions_exceeded"):
        build_write_preview("chatgpt.prompt-batch.message.write", tasks, require_web_search=False, max_actions=1)


def test_timeout_read_back_found_not_found_and_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chatgpt_workflow, "current_browser_url", lambda _book: "https://chatgpt.com/c/found")
    assert chatgpt_workflow.read_back_conversation(object(), "https://chatgpt.com/") == "https://chatgpt.com/c/found"

    monkeypatch.setattr(chatgpt_workflow, "current_browser_url", lambda _book: "https://chatgpt.com/")
    assert chatgpt_workflow.read_back_conversation(object(), "https://chatgpt.com/") is None
    with pytest.raises(WriteSafetyError, match="uncertain_write_outcome"):
        chatgpt_workflow.require_read_back(None)
